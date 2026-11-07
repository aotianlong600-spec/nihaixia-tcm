"""Native mobile model transport. No Node, desktop auth stores or platform imports."""
import base64
from contextlib import closing
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlencode
from uuid import uuid4

from .domain import DomainError
from .model_profiles import DEFAULT_CONFIG, ProfileStore
from .model_urls import CODEX_BASE, validate_url
from .portable_validation import validate
from . import storage

AUTH_BASE = 'https://auth.openai.com'
CLIENT_ID = 'app_EMoamEEZ73f0CkXaXp7hrann'  # Public client ID used by the pinned Pi Codex provider.
DEVICE_URI = AUTH_BASE + '/codex/device'
TOKEN_URI = AUTH_BASE + '/oauth/token'
OUTPUT_LIMIT = 128 * 1024
RESPONSE_LIMIT = 4 * 1024 * 1024


def codex_catalog():
    path = Path(__file__).resolve().parent / 'resources' / 'codex_models.json'
    if not path.is_file():
        return []
    values = json.loads(path.read_text(encoding='utf-8'))
    return [{'id': m['id'], 'name': m['name'], 'reasoning_efforts': m['reasoning_efforts']}
            for m in values if isinstance(m, dict) and isinstance(m.get('id'), str)
            and isinstance(m.get('name'), str) and isinstance(m.get('reasoning_efforts'), list)]


class _SecretBoundary:
    def __init__(self, root, backend):
        self.root, self.backend = root.resolve(), backend

    def _path(self, path):
        path = Path(path)
        if not path.resolve().is_relative_to(self.root):
            raise ValueError('凭据文件不在本机数据目录')
        return path

    def read(self, path):
        try:
            value = self.backend.read(self._path(path))
            if value is not None and not isinstance(value, str):
                raise TypeError()
            return value
        except Exception:
            raise ValueError('本机加密凭据读取失败，请重新配置') from None

    def write(self, path, value):
        try:
            self.backend.write(self._path(path), value)
        except Exception:
            raise ValueError('本机加密凭据保存失败，请检查设备存储') from None


def _sse(raw):
    data = []
    for line in raw.lstrip('\ufeff').split('\n') + ['']:
        line = line.rstrip('\r')
        if not line:
            if data:
                payload = '\n'.join(data)
                if payload == '[DONE]':
                    yield payload
                else:
                    try:
                        value = json.loads(payload)
                    except (ValueError, TypeError):
                        raise ValueError('模型流式响应格式不完整') from None
                    if not isinstance(value, dict):
                        raise ValueError('模型流式响应格式无效')
                    yield value
                data = []
        elif line.startswith('data:'):
            data.append(line[5:].lstrip(' '))


def _usage(value, codex=False):
    if not isinstance(value, dict):
        return {}
    fields = [('input_tokens' if codex else 'prompt_tokens', 'input'),
              ('output_tokens' if codex else 'completion_tokens', 'output'), ('total_tokens', 'totalTokens')]
    return {target: value[source] for source, target in fields
            if type(value.get(source)) is int and value[source] >= 0}


def _credential(value):
    if not isinstance(value, dict) or value.get('type') != 'oauth':
        raise ValueError('Codex授权格式无效')
    for key in ('access', 'refresh'):
        token = value.get(key)
        if not isinstance(token, str) or not token or len(token) > 7000 or any(ord(c) <= 32 or ord(c) == 127 for c in token):
            raise ValueError('Codex授权格式无效')
    expires = value.get('expires')
    if isinstance(expires, bool) or not isinstance(expires, (int, float)) or not math.isfinite(expires) or expires <= 0:
        raise ValueError('Codex授权有效期无效')
    account = value.get('accountId')
    if not isinstance(account, str) or not 1 <= len(account) <= 256 or any(ord(c) <= 32 or ord(c) == 127 for c in account):
        raise ValueError('Codex授权账户信息无效')
    return {key: value[key] for key in ('type', 'access', 'refresh', 'expires', 'accountId')}


class _NativeOAuth:
    def __init__(self, root, request, secrets, cancel):
        self.path = root / 'codex-secret.native'
        self.request, self.secrets, self.cancel_http = request, secrets, cancel
        self.lock, self.refresh_lock = threading.RLock(), threading.Lock()
        self.generation = 0
        self.attempt = None

    def _read(self):
        raw = self.secrets.read(self.path)
        return _credential(json.loads(raw)) if raw else None

    def status(self):
        with self.lock:
            try:
                credential = self._read()
                error = None
            except (ValueError, OSError):
                credential, error = None, '本机Codex授权不可用，请清除后重新登录'
            value = {'logged_in': credential is not None,
                     'expires_at': credential['expires'] / 1000 if credential else None,
                     'requires_refresh': bool(credential and credential['expires'] <= time.time() * 1000 + 60000),
                     'login': self._public_attempt()}
            if error:
                value['credential_error'] = error
            return value

    def _public_attempt(self):
        return {k: deepcopy(v) for k, v in self.attempt.items() if not k.startswith('_')} if self.attempt else None

    def start(self, body):
        if not isinstance(body, dict) or set(body) - {'method'} or body.get('method', 'device') not in ('device', 'browser'):
            raise ValueError('授权方式无效')
        if body.get('method') == 'browser':
            raise DomainError(409, '独立安卓请使用设备码登录，并在系统浏览器完成官方授权')
        with self.lock:
            if self.attempt and self.attempt['status'] == 'pending':
                raise DomainError(409, '已有设备码授权等待完成，请先完成或取消')
            self.generation += 1
            attempt = {'id': uuid4().hex, 'status': 'pending', 'method': 'device', 'stage': 'starting',
                       '_cancel': threading.Event(), '_generation': self.generation}
            self.attempt = attempt
        threading.Thread(target=self._login, args=(attempt,), daemon=True).start()
        with self.lock:
            return self._public_attempt()

    def _check(self, attempt):
        if attempt['_cancel'].is_set() or self.generation != attempt['_generation']:
            raise ValueError('本次授权已取消')

    def _json(self, url, value, request_id, form=False):
        body = urlencode(value) if form else storage.encode(value)
        headers = {'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json', 'Accept': 'application/json'}
        response = self.request('POST', url, headers, body, request_id, 30000)
        try:
            data = json.loads(response['body'])
        except (ValueError, TypeError):
            if not 200 <= response['status'] < 300:
                return response['status'], None
            raise ValueError('OpenAI授权响应格式不完整') from None
        if not isinstance(data, dict):
            if not 200 <= response['status'] < 300:
                return response['status'], None
            raise ValueError('OpenAI授权响应格式无效')
        return response['status'], data

    @staticmethod
    def _from_token(value):
        if not isinstance(value, dict):
            raise ValueError('OpenAI授权字段不完整')
        expiry = value.get('expires_in')
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry) or expiry <= 0:
            raise ValueError('OpenAI授权有效期无效')
        try:
            part = value['access_token'].split('.')[1]
            payload = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
            account = payload['https://api.openai.com/auth']['chatgpt_account_id']
        except (KeyError, IndexError, ValueError, TypeError, AttributeError):
            raise ValueError('OpenAI返回的账户信息无法识别') from None
        return _credential({'type': 'oauth', 'access': value.get('access_token'), 'refresh': value.get('refresh_token'),
                            'expires': time.time() * 1000 + expiry * 1000, 'accountId': account})

    def _login(self, attempt):
        request_id = 'oauth:' + attempt['id']
        try:
            status, device = self._json(AUTH_BASE + '/api/accounts/deviceauth/usercode', {'client_id': CLIENT_ID}, request_id)
            if status != 200 or not device:
                raise ValueError('OpenAI设备码申请未完成')
            internal = device.get('device_auth_id')
            code = device.get('user_code')
            try:
                if isinstance(device.get('interval'), bool):
                    raise ValueError()
                interval = float(device.get('interval', 5))
            except (ValueError, TypeError):
                raise ValueError('OpenAI设备码等待间隔无效') from None
            if (not isinstance(internal, str) or not 1 <= len(internal) <= 2000 or not isinstance(code, str)
                    or not re.fullmatch(r'[A-Za-z0-9-]{1,64}', code) or not math.isfinite(interval) or interval < 0):
                raise ValueError('OpenAI设备码字段无效')
            interval = max(1, interval)
            deadline = time.monotonic() + 900
            with self.lock:
                self._check(attempt)
                attempt.update(stage='waiting_authorization', device_code={'code': code, 'url': DEVICE_URI}, auth_url=DEVICE_URI)
            while time.monotonic() < deadline:
                self._check(attempt)
                status, grant = self._json(AUTH_BASE + '/api/accounts/deviceauth/token',
                                           {'device_auth_id': internal, 'user_code': code}, request_id)
                self._check(attempt)
                if status == 200:
                    if not grant or not all(isinstance(grant.get(k), str) and 1 <= len(grant[k]) <= 7000 for k in ('authorization_code', 'code_verifier')):
                        raise ValueError('OpenAI授权回传字段不完整')
                    with self.lock:
                        self._check(attempt)
                        attempt['stage'] = 'exchanging_token'
                    status, token = self._json(TOKEN_URI, {'grant_type': 'authorization_code', 'client_id': CLIENT_ID,
                        'code': grant['authorization_code'], 'code_verifier': grant['code_verifier'],
                        'redirect_uri': AUTH_BASE + '/deviceauth/callback'}, request_id, form=True)
                    if status != 200:
                        raise ValueError('OpenAI授权令牌兑换未完成')
                    credential = self._from_token(token)
                    with self.lock:
                        self._check(attempt)
                        attempt['stage'] = 'saving_credential'
                        self.secrets.write(self.path, storage.encode(credential))
                        self.generation += 1
                        attempt.update(status='completed', stage='completed')
                    return
                code = grant.get('error') if grant else None
                code = code.get('code') if isinstance(code, dict) else code
                if code == 'slow_down':
                    interval += 5
                elif status not in (403, 404) and code not in ('authorization_pending', 'deviceauth_authorization_pending'):
                    raise ValueError('OpenAI设备授权未完成，请在官方页面检查授权状态')
                attempt['_cancel'].wait(min(interval, max(0, deadline - time.monotonic())))
            raise ValueError('设备码授权已超时，请重新发起')
        except Exception:
            with self.lock:
                if attempt.get('status') == 'pending':
                    attempt.update(status='cancelled' if attempt['_cancel'].is_set() else 'failed',
                                   error='本次设备码授权未完成；请核对网络、官方页面或重新发起授权')

    def cancel(self, login_id):
        with self.lock:
            if not self.attempt or self.attempt['id'] != login_id:
                raise DomainError(409, '当前没有匹配的设备码授权')
            if self.attempt['status'] == 'pending':
                self.attempt['_cancel'].set()
                self.attempt.update(status='cancelled', stage='cancelled')
                self.generation += 1
                self.cancel_http('oauth:' + login_id)
            return self._public_attempt()

    def logout(self):
        with self.lock:
            if self.attempt and self.attempt['status'] == 'pending':
                self.cancel(self.attempt['id'])
            self.generation += 1
            self.cancel_http('oauth:refresh')
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                raise ValueError('本机授权文件未能移除，请检查设备存储') from None
            return {'logged_in': False}

    def access_token(self):
        with self.refresh_lock:
            with self.lock:
                try:
                    value = self._read()
                except (ValueError, OSError):
                    raise DomainError(409, '本机Codex授权不可用，请清除后重新登录') from None
                generation = self.generation
            if not value:
                raise DomainError(409, '请先完成本机Codex设备码授权')
            if value['expires'] > time.time() * 1000 + 60000:
                return value['access'], value['accountId'], generation
            status, token = self._json(TOKEN_URI, {'grant_type': 'refresh_token', 'refresh_token': value['refresh'],
                                                 'client_id': CLIENT_ID}, 'oauth:refresh', form=True)
            if status != 200:
                raise DomainError(409, 'Codex授权刷新失败，请重新登录')
            fresh = self._from_token(token)
            with self.lock:
                if self.generation != generation or fresh['accountId'] != value['accountId']:
                    raise DomainError(409, 'Codex授权已变化，请重新发送')
                self.secrets.write(self.path, storage.encode(fresh))
            return fresh['access'], fresh['accountId'], generation


class MobileModels:
    def __init__(self, data_dir, http, secrets):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.http = http
        self.secrets = _SecretBoundary(self.data_dir, secrets)
        self.profiles = ProfileStore(self.data_dir, validate_url, self.secrets)
        self.guard = threading.RLock()
        self.jobs = {}
        self.oauth = _NativeOAuth(self.data_dir, self._request, self.secrets, self._cancel_http)

    def _cancel_http(self, request_id):
        cancel = getattr(self.http, 'cancel', None)
        if cancel:
            try:
                cancel(request_id)
            except Exception:
                pass

    def _request(self, method, url, headers, body, request_id, timeout_ms):
        try:
            value = self.http(method, url, headers, body, request_id, timeout_ms)
            if not isinstance(value, dict) or type(value.get('status')) is not int or not 100 <= value['status'] <= 599:
                raise TypeError()
            if not isinstance(value.get('body'), str) or len(value['body'].encode('utf-8')) > RESPONSE_LIMIT:
                raise TypeError()
            if not isinstance(value.get('headers', {}), dict):
                raise TypeError()
            return value
        except Exception:
            raise ValueError('模型网络请求未完成或响应超限，请核对地址和网络') from None

    def public_config(self):
        snapshot = self.profiles.snapshot()
        item = next((p for p in snapshot['items'] if p['id'] == snapshot['active_id']), None)
        value = {k: item[k] for k in DEFAULT_CONFIG} if item else dict(DEFAULT_CONFIG)
        value.update(profile_id=item['id'] if item else None, profile_name=item['name'] if item else None,
                     profile_revision=snapshot['revision'], has_key=bool(item and self.profiles.has_key(item['id'])))
        value['codex'] = self.oauth.status()
        value['has_oauth'] = value['codex']['logged_in']
        value['key_hint'] = '已由设备系统加密保存' if value['has_key'] else '未配置'
        return value

    @staticmethod
    def _payload(name, body):
        value = validate(name, body if body is not None else {})
        key = value.get('api_key')
        if key and any(ord(c) <= 32 or ord(c) == 127 for c in key):
            raise ValueError('API密钥包含无效字符')
        if value.get('model') and any(ord(c) < 32 or ord(c) == 127 for c in value['model']):
            raise ValueError('模型ID包含无效字符')
        return value

    def handle(self, method, path, body=None):
        try:
            return self._handle(method.upper(), path, body)
        except DomainError as exc:
            return exc.status_code, {'detail': exc.detail}
        except ValueError as exc:
            return 400, {'detail': str(exc)[:500]}
        except Exception:
            return 500, {'detail': '本机模型服务未完成请求，请检查配置或设备存储'}

    def _handle(self, method, path, body):
        if path == '/model/config' and method == 'GET':
            return 200, self.public_config()
        if path == '/model/config' and method == 'PUT':
            value = self._payload('ModelConfig', body)
            fields = {k: value[k] for k in DEFAULT_CONFIG}
            with self.guard:
                snapshot = self.profiles.snapshot()
                item = next((p for p in snapshot['items'] if p['id'] == snapshot['active_id']), None)
                if item:
                    self.profiles.update(item['id'], fields, item['name'], value['api_key'])
                else:
                    self.profiles.create(fields, '默认配置', value['api_key'], activate=True)
                return 200, self.public_config()
        if path == '/model/profiles':
            if method == 'GET':
                return 200, self.profiles.list()
            if method == 'POST':
                value = self._payload('ProfileInput', body)
                with self.guard:
                    return 200, self.profiles.create({k: value[k] for k in DEFAULT_CONFIG}, value['name'], value['api_key'])
        match = re.fullmatch(r'/model/profiles/([^/]+)(/select)?', path)
        if match:
            profile_id, select = match.groups()
            with self.guard:
                if select and method == 'POST':
                    self.profiles.select(profile_id)
                    return 200, self.public_config()
                if not select and method == 'DELETE':
                    result = self.profiles.delete(profile_id)
                    for job in self.jobs.values():
                        if job.get('profile_id') == profile_id:
                            self._cancel_job(job)
                    return 200, result
                if not select and method == 'PUT':
                    value = self._payload('ProfileUpdate', body)
                    if value['expected_profile_revision'] is not None and value['expected_profile_revision'] != self.profiles.snapshot()['revision']:
                        raise DomainError(409, '模型配置已更改，请刷新后重新应用')
                    return 200, self.profiles.update(profile_id, {k: value[k] for k in DEFAULT_CONFIG}, value['name'], value['api_key'])
        if path == '/model/codex' and method == 'GET':
            return 200, self.oauth.status()
        if path == '/model/codex/models' and method == 'GET':
            return 200, {'items': codex_catalog(), 'scope': 'SDK静态模型目录，不保证账号权限；以实际请求为准'}
        if path == '/model/codex/login' and method == 'POST':
            return 200, self.oauth.start({} if body is None else body)
        if path == '/model/codex/logout' and method == 'POST':
            with self.guard:
                for job in self.jobs.values():
                    if job.get('auth_mode') == 'codex':
                        self._cancel_job(job)
                return 200, self.oauth.logout()
        match = re.fullmatch(r'/model/codex/login/([^/]+)/(cancel|code)', path)
        if match and method == 'POST':
            if match[2] == 'code':
                raise DomainError(409, '设备码请填写在OpenAI官方页面，独立安卓不接受电脑浏览器回调')
            return 200, self.oauth.cancel(match[1])
        if path == '/model/jobs' and method == 'POST':
            return 200, self._start_job(self._payload('JobInput', body))
        match = re.fullmatch(r'/model/jobs/([^/]+)(/cancel)?', path)
        if match:
            if match[2] and method == 'POST':
                with self.guard:
                    job = self.jobs.get(match[1])
                    if not job:
                        raise DomainError(404, '模型任务不存在')
                    self._cancel_job(job)
                    return 200, self._public_job(job)
            if not match[2] and method == 'GET':
                return 200, self._get_job(match[1])
        raise DomainError(404, '模型接口不存在')

    def _cancel_job(self, job):
        if job['status'] in ('queued', 'running'):
            job['_cancel'].set()
            job.update(status='cancelled', validated=False)
            self._cancel_http(job['id'])

    @staticmethod
    def _public_job(job):
        fields = ('id','status','text','error','usage','validated','validation_scope','created_at','stale',
                  'dependency_warnings','analysis_id','consultation_id','result','evidence','profile_id',
                  'profile_name','profile_revision','reasoning_effort')
        value = {k: deepcopy(job[k]) for k in fields if k in job}
        if job.get('purpose') == 'consult' and job['status'] != 'completed':
            value['text'] = ''
        return value

    @staticmethod
    def _match_snapshot(snapshot, profile_id, revision):
        if snapshot['active_id'] != profile_id or snapshot['revision'] != revision:
            raise DomainError(409, '模型配置已更改，请刷新后重新发送')

    def _start_job(self, payload):
        if payload['purpose'] not in ('test', 'consult', 'explain'):
            raise DomainError(400, '不支持的模型任务')
        snapshot = self.profiles.snapshot()
        selected = next((p for p in snapshot['items'] if p['id'] == snapshot['active_id']), None)
        if not selected:
            raise DomainError(409, '当前未选择模型配置')
        profile_id, revision = selected['id'], snapshot['revision']
        if payload['expected_profile_id'] is not None or payload['expected_profile_revision'] is not None:
            self._match_snapshot(snapshot, payload['expected_profile_id'], payload['expected_profile_revision'])
        cfg = {k: selected[k] for k in DEFAULT_CONFIG}
        validate_url(cfg['base_url'])
        if cfg['auth_mode'] == 'codex' and cfg['reasoning_effort'] != 'auto':
            known = next((m for m in codex_catalog() if m['id'] == cfg['model']), None)
            if not known or cfg['reasoning_effort'] not in known['reasoning_efforts']:
                raise DomainError(409, '所选Codex模型不支持此思考档位，请改为模型默认或支持的档位')
        request_input = 'Synthetic integration test only. Reply: Connection works.'
        system = 'Reply with a short synthetic connection-test confirmation.'
        context, analysis, allowed = None, None, set()
        if payload['purpose'] != 'test':
            if not cfg['enabled'] or not cfg['allow_external'] or not payload['allow_send']:
                raise DomainError(403, '请先启用接口并允许本次发送必要信息')
            with closing(storage.connect(self.data_dir)) as conn:
                if payload['purpose'] == 'consult':
                    if not cfg['allow_evidence'] or not payload['consultation_id']:
                        raise DomainError(403, '问诊需要允许发送书证并关联问诊记录')
                    from . import consultation_core as core
                    context, request_input, system = core.prepare_task(conn, payload['consultation_id'])
                    allowed = {e['id'] for e in context['evidence']}
                else:
                    row = conn.execute('SELECT document FROM analyses WHERE id=?', (payload['analysis_id'],)).fetchone()
                    if not row:
                        raise DomainError(404, '分析不存在')
                    analysis = json.loads(row['document'])
                    if storage.analysis_dependency_errors(conn, analysis):
                        raise DomainError(409, '分析输入或来源已更改，请重新分析')
                    allowed = {e['id'] for e in analysis.get('evidence_snapshot', [])}
                    facts = [{k: f[k] for k in ('key','state','value','unit','scope') if k in f}
                             for f in analysis['input_snapshot']['facts'] if f.get('verified') is True
                             and f.get('scope','current') == 'current' and f.get('subject','patient') == 'patient']
                    request_input = storage.encode({'facts':facts,'candidates':analysis['result'].get('candidates',[]),
                        'evidence':[{'id':e['id'],**({'quote':e['quote']} if cfg['allow_evidence'] else {})} for e in analysis.get('evidence_snapshot',[])]})
                    system = '只返回JSON对象，字段严格为summary字符串、questions字符串数组、evidence_ids字符串数组；不得添加患者事实或药量。'
        with self.guard:
            self._match_snapshot(self.profiles.snapshot(), profile_id, revision)
            if sum(not j['_done'].is_set() for j in self.jobs.values()) >= 2:
                raise DomainError(429, '已有模型任务运行，请完成或取消后重试')
        key, account, auth_generation = None, None, None
        if cfg['auth_mode'] == 'codex':
            # Register the job before any network refresh so the UI always owns its ID.
            with self.oauth.lock:
                try:
                    credential = self.oauth._read()
                except (ValueError, OSError):
                    raise DomainError(409, '本机Codex授权不可用，请清除后重新登录') from None
                if not credential:
                    raise DomainError(409, '请先完成本机Codex设备码授权')
                account, auth_generation = credential['accountId'], self.oauth.generation
        else:
            key = self.profiles.read_key(profile_id)
            if not key:
                raise DomainError(409, '请先保存本配置的API密钥')
        with self.guard:
            self._match_snapshot(self.profiles.snapshot(), profile_id, revision)
            if auth_generation is not None and auth_generation != self.oauth.generation:
                raise DomainError(409, 'Codex授权已更改，请重新发送')
            if sum(not j['_done'].is_set() for j in self.jobs.values()) >= 2:
                raise DomainError(429, '已有模型任务运行，请稍后重试')
            if len(self.jobs) >= 100:
                old = next((i for i, j in self.jobs.items() if j['_done'].is_set()), None)
                if old:
                    self.jobs.pop(old)
            job = {'id':str(uuid4()),'status':'queued','text':'','validated':False,'purpose':payload['purpose'],
                   'created_at':storage.now(),'profile_id':profile_id,'profile_name':selected['name'],
                   'profile_revision':revision,'reasoning_effort':cfg['reasoning_effort'],'auth_mode':cfg['auth_mode'],
                   'analysis_id':payload['analysis_id'],'_cancel':threading.Event(),'_done':threading.Event(),
                   '_auth_generation':auth_generation}
            if context:
                job.update(consultation_id=payload['consultation_id'], consultation_context=context)
            self.jobs[job['id']] = job
        threading.Thread(target=self._run_job, args=(job, deepcopy(cfg), key, account, request_input, system, context, analysis, allowed), daemon=True).start()
        return self._public_job(job)

    def _model_response(self, job, cfg, key, account, request_input, system):
        if job['_cancel'].is_set():
            raise ValueError('模型任务已取消')
        codex = cfg['auth_mode'] == 'codex'
        headers = {'Authorization':'Bearer '+key, 'Content-Type':'application/json', 'Accept':'text/event-stream'}
        if codex:
            effort = cfg['reasoning_effort']
            endpoint = CODEX_BASE + '/codex/responses'
            headers.update({'ChatGPT-Account-Id':account, 'OpenAI-Beta':'responses=experimental', 'originator':'nihaixia-tcm-local'})
            body = {'model':cfg['model'],'store':False,'stream':True,'instructions':system,
                    'input':[{'role':'user','content':[{'type':'input_text','text':request_input}]}],
                    'tools':[],'tool_choice':'none','text':{'verbosity':'low'}}
            if effort != 'auto':
                body['reasoning'] = {'effort':effort}
        else:
            endpoint = cfg['base_url'].rstrip('/') + '/chat/completions'
            body = {'model':cfg['model'],'stream':True,'messages':[{'role':'system','content':system},{'role':'user','content':request_input}],
                    'max_tokens':4096 if job['purpose']=='consult' else 2048}
            if cfg['reasoning_effort'] != 'auto':
                body['reasoning_effort'] = cfg['reasoning_effort']
        response = self._request('POST', endpoint, headers, storage.encode(body), job['id'], 90000)
        if job['_cancel'].is_set():
            raise ValueError('模型任务已取消')
        status = response['status']
        if not 200 <= status < 300:
            raise ValueError(f'模型请求失败（HTTP {status}），请核对模型权限、额度或接口地址')
        content_type = next((str(v).lower() for k, v in response.get('headers',{}).items() if k.lower()=='content-type'), '')
        if (not codex and 'text/event-stream' not in content_type) or (codex and content_type and 'text/event-stream' not in content_type):
            raise ValueError('模型没有返回受支持的流式响应')
        text, done, stopped, usage = '', False, False, {}
        for event in _sse(response['body']):
            if job['_cancel'].is_set():
                raise ValueError('模型任务已取消')
            if event == '[DONE]':
                if not codex:
                    if done:
                        raise ValueError('模型返回重复的终止标记')
                    done = True
                continue
            if done:
                raise ValueError('模型在完成终态之后仍返回额外数据')
            if codex:
                kind = event.get('type','')
                if kind in ('error','response.failed','response.incomplete') or 'function_call' in kind or 'tool_call' in kind:
                    raise ValueError('Codex响应未完整完成或包含不支持的工具调用')
                item = event.get('item',{})
                if item.get('type') in ('function_call','custom_tool_call','tool_call'):
                    raise ValueError('当前通道不执行模型工具调用')
                if kind == 'response.output_text.delta':
                    text += str(event.get('delta',''))
                if kind in ('response.completed','response.done'):
                    final = event.get('response',{})
                    if final.get('status') != 'completed':
                        raise ValueError('Codex响应未到达完成状态')
                    output = final.get('output',[])
                    if any(o.get('type') not in ('message','reasoning') for o in output):
                        raise ValueError('当前通道不执行模型工具调用')
                    final_text = ''.join(part.get('text','') for o in output if o.get('type')=='message'
                                         for part in o.get('content',[]) if part.get('type')=='output_text')
                    if final_text and text and final_text != text:
                        raise ValueError('Codex完成内容与流式内容不一致')
                    text = final_text or text
                    usage = _usage(final.get('usage'), True)
                    done = stopped = True
            else:
                if event.get('error'):
                    raise ValueError('模型返回错误响应，本次结果未保存')
                if event.get('usage') is not None:
                    usage = _usage(event['usage'])
                for choice in event.get('choices',[]):
                    if choice.get('index',0) != 0:
                        raise ValueError('模型返回多个候选流，当前通道不支持')
                    delta = choice.get('delta',{})
                    if delta.get('tool_calls') or delta.get('function_call'):
                        raise ValueError('当前通道不执行模型工具调用')
                    part = delta.get('content')
                    if part is not None:
                        if stopped and part:
                            raise ValueError('模型在停止之后仍返回额外内容')
                        if not isinstance(part,str):
                            raise ValueError('模型输出格式不受支持')
                        text += part
                    finish = choice.get('finish_reason')
                    if finish is not None:
                        if finish != 'stop' or stopped:
                            raise ValueError('模型响应未正常结束，本次结果未保存')
                        stopped = True
            if len(text.encode('utf-8')) > OUTPUT_LIMIT:
                raise ValueError('模型输出超过本机大小限制')
        if not done or not stopped or not text.strip():
            raise ValueError('模型响应缺少完整终止标记或有效内容')
        return text, usage

    def _run_job(self, job, cfg, key, account, request_input, system, context, analysis, allowed):
        try:
            with self.guard:
                if job['_cancel'].is_set():
                    return
                job['status'] = 'running'
            if context:
                from . import consultation_core as core
                with closing(storage.connect(self.data_dir)) as conn:
                    if core.task_warnings(conn, context):
                        raise ValueError('问诊或书证已变化，请重新发送')
            if cfg['auth_mode'] == 'codex':
                with self.oauth.lock:
                    if self.oauth.generation != job['_auth_generation']:
                        raise ValueError('Codex授权已变化，请重新发送')
                key, refreshed_account, generation = self.oauth.access_token()
                with self.guard:
                    if job['_cancel'].is_set():
                        return
                    if (generation != job['_auth_generation'] or self.oauth.generation != generation
                            or refreshed_account != account):
                        raise ValueError('Codex授权已变化，请重新发送')
            text, usage = self._model_response(job, cfg, key, account, request_input, system)
            result = None
            if job['purpose'] == 'consult':
                try:
                    result = core.validate_result(validate('ConsultResult', json.loads(text)), context)
                except (TypeError, json.JSONDecodeError):
                    raise ValueError('模型输出不是完整问诊JSON，本次结果未保存') from None
            elif job['purpose'] == 'explain':
                result = json.loads(text)
                if (not isinstance(result,dict) or set(result)!={'summary','questions','evidence_ids'}
                        or not isinstance(result['summary'],str) or not 1 <= len(result['summary']) <= 30000
                        or any(not isinstance(result[k],list) or len(result[k])>100 or any(not isinstance(v,str) or len(v)>2000 for v in result[k]) for k in ('questions','evidence_ids'))
                        or set(result['evidence_ids']) - allowed):
                    raise ValueError('模型解释结构或引用不符合本次冻结资料')
            with self.guard:
                if job['_cancel'].is_set():
                    return
                finished = {**self._public_job(job),'status':'completed','text':text,'usage':usage,'validated':True,
                            'validation_scope':'仅完成、结构、引用及来源检查，不代表医学有效性','result':result}
                if context:
                    finished.update(text=storage.encode(result), evidence=context['evidence'])
                with closing(storage.connect(self.data_dir)) as conn, conn:
                    conn.execute('BEGIN IMMEDIATE')
                    if (context and core.task_warnings(conn, context)) or (analysis and storage.analysis_dependency_errors(conn, analysis)):
                        raise ValueError('问诊输入或来源已更改，本次结果未保存，请重新分析')
                    document = {**finished,'purpose':job['purpose'],'model':cfg['model'],'recipient':cfg['base_url']}
                    if context:
                        document.update(consultation_context=context,raw_response=text)
                        core.save_assistant_result(conn, job, result, context)
                    conn.execute('INSERT INTO model_calls VALUES(?,?,?,?,?,?)',(job['id'],job.get('analysis_id'),job['purpose'],'completed',storage.encode(document),job['created_at']))
                    storage.audit(conn,'model_completed',job['id'],purpose=job['purpose'])
                job.update(finished)
        except Exception as exc:
            with self.guard:
                job.update(status='cancelled' if job['_cancel'].is_set() else 'failed',validated=False)
                if not job['_cancel'].is_set():
                    job['error'] = str(exc)[:500] if isinstance(exc,(ValueError,DomainError)) else '本机模型通道未完成，本次结果未保存'
        finally:
            job['_done'].set()

    def _get_job(self, job_id):
        with self.guard:
            job = dict(self.jobs[job_id]) if job_id in self.jobs else None
        with closing(storage.connect(self.data_dir)) as conn:
            if job is None:
                row = conn.execute('SELECT document FROM model_calls WHERE id=?',(job_id,)).fetchone()
                if not row:
                    raise DomainError(404,'模型任务不存在')
                job = json.loads(row['document'])
            warnings = []
            if job.get('consultation_context'):
                from . import consultation_core as core
                warnings = core.task_warnings(conn,job['consultation_context'])
            elif job.get('analysis_id'):
                row = conn.execute('SELECT document FROM analyses WHERE id=?',(job['analysis_id'],)).fetchone()
                warnings = storage.analysis_dependency_errors(conn,json.loads(row['document'])) if row else ['关联分析已不存在']
            if warnings:
                job.update(stale=True,dependency_warnings=warnings,validated=False)
            return self._public_job(job)
