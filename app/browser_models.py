"""Python model jobs whose HTTP requests are executed by the browser worker."""
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import json
import math
import os
import re
import tempfile
import threading
import time
from urllib.parse import urlencode
from uuid import uuid4

from . import consultation_core as core, storage
from .domain import DomainError
from .mobile_models import AUTH_BASE, CLIENT_ID, DEVICE_URI, TOKEN_URI, MobileModels, _NativeOAuth, _SecretBoundary
from .model_profiles import ProfileStore
from .model_urls import validate_url


class BrowserSecrets:
    """Only the virtual filesystem; the worker encrypts its persisted snapshot."""
    def read(self, path):
        path = Path(path)
        return path.read_text(encoding='utf-8') if path.is_file() else None

    def write(self, path, value):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.credential-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                output.write(value)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)


class BrowserOAuth(_NativeOAuth):
    def __init__(self, owner, root, secrets):
        super().__init__(root, None, secrets, owner._cancel_http)
        self.owner = owner
        self.refresh = None
        self.session_path = root / 'codex-session'

    def session(self):
        return self.session_path.read_text(encoding='utf-8') if self.session_path.is_file() else ''

    def _rotate_session(self):
        self.session_path.write_text(uuid4().hex, encoding='utf-8')

    def logout(self):
        result = super().logout()
        self._rotate_session()
        return result

    def _json_request(self, url, value, callback, failure, valid, form=False, delay_ms=0):
        headers = {'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json', 'Accept': 'application/json'}
        body = urlencode(value) if form else storage.encode(value)
        def completed(response):
            try:
                data = json.loads(response['body'])
            except (ValueError, TypeError):
                data = None
            if not isinstance(data, dict):
                if 200 <= response['status'] < 300:
                    raise ValueError('OpenAI授权响应格式不完整')
                data = None
            callback(response['status'], data)
        self.owner._queue_request('POST', url, headers, body, 30000, completed, failure, valid, delay_ms)

    def start(self, body):
        if not isinstance(body, dict) or set(body) - {'method'} or body.get('method', 'device') not in ('device', 'browser'):
            raise ValueError('授权方式无效')
        if body.get('method') == 'browser':
            raise DomainError(409, '公开网页请使用设备码登录，并在官方页面完成授权')
        if self.attempt and self.attempt['status'] == 'pending':
            raise DomainError(409, '已有设备码授权等待完成，请先完成或取消')
        self.generation += 1
        self._rotate_session()
        attempt = {'id': uuid4().hex, 'status': 'pending', 'method': 'device', 'stage': 'starting',
                   '_cancel': threading.Event(), '_generation': self.generation, '_session': self.session(),
                   '_deadline': time.monotonic() + 900}
        self.attempt = attempt
        self._json_request(AUTH_BASE + '/api/accounts/deviceauth/usercode', {'client_id': CLIENT_ID},
                           lambda status, data: self._device_code(attempt, status, data),
                           lambda error: self._login_failed(attempt), lambda: self._check(attempt))
        return self._public_attempt()

    def _check(self, attempt):
        super()._check(attempt)
        if attempt['_session'] != self.session():
            raise ValueError('Codex授权已变化，请重新登录')
        if attempt['status'] != 'pending':
            raise ValueError('本次授权已结束')
        if time.monotonic() >= attempt['_deadline']:
            raise ValueError('设备码授权已超时，请重新发起')

    def _login_failed(self, attempt):
        if attempt['status'] == 'pending':
            attempt.update(status='cancelled' if attempt['_cancel'].is_set() else 'failed',
                           error='本次设备码授权未完成；请核对网络、官方页面或重新发起授权')

    def _device_code(self, attempt, status, data):
        self._check(attempt)
        if status != 200 or not data:
            raise ValueError('OpenAI设备码申请未完成')
        internal, code = data.get('device_auth_id'), data.get('user_code')
        interval = data.get('interval', 5)
        if isinstance(interval, bool):
            raise ValueError('OpenAI设备码等待间隔无效')
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            raise ValueError('OpenAI设备码等待间隔无效') from None
        if (not isinstance(internal, str) or not 1 <= len(internal) <= 2000 or not isinstance(code, str)
                or not re.fullmatch(r'[A-Za-z0-9-]{1,64}', code) or not math.isfinite(interval) or interval < 0):
            raise ValueError('OpenAI设备码字段无效')
        attempt.update(stage='waiting_authorization', device_code={'code': code, 'url': DEVICE_URI}, auth_url=DEVICE_URI,
                       user_code=code, verification_uri=DEVICE_URI,
                       expires_at=time.time() + max(0, attempt['_deadline'] - time.monotonic()),
                       _device_auth_id=internal, _interval=max(1, interval))
        self._poll_device(attempt)

    def _poll_device(self, attempt):
        self._check(attempt)
        self._json_request(AUTH_BASE + '/api/accounts/deviceauth/token',
                           {'device_auth_id': attempt['_device_auth_id'], 'user_code': attempt['user_code']},
                           lambda status, data: self._device_grant(attempt, status, data),
                           lambda error: self._login_failed(attempt), lambda: self._check(attempt),
                           delay_ms=int(min(attempt['_interval'], max(0, attempt['_deadline'] - time.monotonic())) * 1000))

    def _device_grant(self, attempt, status, data):
        self._check(attempt)
        if status == 200:
            if not data or not all(isinstance(data.get(k), str) and 1 <= len(data[k]) <= 7000 for k in ('authorization_code', 'code_verifier')):
                raise ValueError('OpenAI授权回传字段不完整')
            attempt['stage'] = 'exchanging_token'
            self._json_request(TOKEN_URI, {'grant_type': 'authorization_code', 'client_id': CLIENT_ID,
                               'code': data['authorization_code'], 'code_verifier': data['code_verifier'],
                               'redirect_uri': AUTH_BASE + '/deviceauth/callback'},
                               lambda status, data: self._device_token(attempt, status, data),
                               lambda error: self._login_failed(attempt), lambda: self._check(attempt), form=True)
            return
        error = data.get('error') if data else None
        error = error.get('code') if isinstance(error, dict) else error
        if error == 'slow_down':
            attempt['_interval'] += 5
        elif status not in (403, 404) and error not in ('authorization_pending', 'deviceauth_authorization_pending'):
            raise ValueError('OpenAI设备授权未完成，请在官方页面检查授权状态')
        self._poll_device(attempt)

    def _device_token(self, attempt, status, data):
        self._check(attempt)
        if status != 200:
            raise ValueError('OpenAI授权令牌兑换未完成')
        value = self._from_token(data)
        attempt['stage'] = 'saving_credential'
        self.secrets.write(self.path, storage.encode(value))
        self.generation += 1
        attempt.update(status='completed', stage='completed')

    def ensure_access(self, job, ready, failure):
        value = self._read()
        if not value:
            raise ValueError('请先完成本机Codex设备码授权')
        if value['expires'] > time.time() * 1000 + 60000:
            ready(value['access'], value['accountId'])
            return
        waiter = (job, ready, failure)
        if self.refresh and self.refresh['generation'] == self.generation:
            self.refresh['waiters'].append(waiter)
            return
        refresh = {'generation': self.generation, 'session': self.session(), 'credential': value, 'waiters': [waiter]}
        self.refresh = refresh
        self._json_request(TOKEN_URI, {'grant_type': 'refresh_token', 'refresh_token': value['refresh'], 'client_id': CLIENT_ID},
                           lambda status, data: self._refreshed(refresh, status, data),
                           lambda error: self._refresh_failed(refresh), lambda: self._check_refresh(refresh), form=True)

    def _check_refresh(self, refresh):
        current = self._read()
        if (refresh is not self.refresh or refresh['generation'] != self.generation or refresh['session'] != self.session() or not current
                or current['accountId'] != refresh['credential']['accountId'] or current['refresh'] != refresh['credential']['refresh']):
            raise ValueError('Codex授权已变化，请重新发送')
        if not any(not job['_cancel'].is_set() and not job['_done'].is_set() for job, _, _ in refresh['waiters']):
            raise ValueError('模型任务已取消')

    def _refresh_failed(self, refresh):
        if self.refresh is refresh:
            self.refresh = None
        for _, _, failure in refresh['waiters']:
            failure(ValueError('Codex授权刷新失败，请重新登录'))

    def _refreshed(self, refresh, status, data):
        self._check_refresh(refresh)
        if status != 200:
            raise ValueError('Codex授权刷新失败，请重新登录')
        value = self._from_token(data)
        if value['accountId'] != refresh['credential']['accountId']:
            raise ValueError('Codex授权账户已变化，请重新登录')
        self.secrets.write(self.path, storage.encode(value))
        self.refresh = None
        for job, ready, failure in refresh['waiters']:
            try:
                self.owner._check_job(job)
                ready(value['access'], value['accountId'])
            except Exception as error:
                failure(error)


class BrowserModels(MobileModels):
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        root = self.data_dir / 'models'
        root.mkdir(parents=True, exist_ok=True)
        self.secrets = _SecretBoundary(root, BrowserSecrets())
        self.profiles = ProfileStore(root, validate_url, self.secrets)
        self.guard = threading.RLock()
        self.jobs, self.requests, self.outbox = {}, {}, []
        self.oauth = BrowserOAuth(self, root, self.secrets)

    def public_config(self):
        value = super().public_config()
        value['key_hint'] = '已保存在当前浏览器的加密存储' if value['has_key'] else '未配置'
        return value

    def _cancel_http(self, request_id):
        # Pending callbacks check their owning job or login before any side effect.
        pass

    def _cancel_job(self, job):
        super()._cancel_job(job)
        job['_done'].set()

    def _queue_request(self, method, url, headers, body, timeout_ms, completed, failed, valid, delay_ms=0):
        request_id = uuid4().hex
        spec = {'id': request_id, 'method': method, 'url': url, 'headers': headers, 'body': body, 'timeout_ms': timeout_ms}
        if delay_ms:
            spec['delay_ms'] = delay_ms
        self.requests[request_id] = (spec, completed, failed, valid)
        self.outbox.append(request_id)

    def take_requests(self):
        queued, self.outbox = self.outbox, []
        result = []
        for request_id in queued:
            pending = self.requests.get(request_id)
            if not pending:
                continue
            spec, _, failed, valid = pending
            try:
                valid()
                result.append(spec)
            except Exception as error:
                self.requests.pop(request_id, None)
                failed(error)
        return result

    def pending_request_ids(self):
        for request_id, (_, _, failed, valid) in list(self.requests.items()):
            try:
                valid()
            except Exception as error:
                self.requests.pop(request_id, None)
                failed(error)
        return list(self.requests)

    def checkpoint(self):
        # Keep object identities: pending Python callbacks close over these dictionaries.
        states = []
        for value in [*self.jobs.values(), *([self.oauth.attempt] if self.oauth.attempt else [])]:
            events = {k: (v, v.is_set()) for k, v in value.items() if k in ('_cancel', '_done')}
            states.append((value, deepcopy({k: v for k, v in value.items() if k not in events}), events))
        refresh = self.oauth.refresh
        return {'jobs': dict(self.jobs), 'states': states, 'requests': dict(self.requests), 'outbox': list(self.outbox),
                'generation': self.oauth.generation, 'attempt': self.oauth.attempt, 'refresh': refresh,
                'refresh_state': {**refresh, 'waiters': list(refresh['waiters'])} if refresh else None}

    def restore_checkpoint(self, checkpoint):
        for value, state, events in checkpoint['states']:
            value.clear()
            value.update(state)
            for key, (event, was_set) in events.items():
                event.set() if was_set else event.clear()
                value[key] = event
        self.jobs = dict(checkpoint['jobs'])
        self.requests = dict(checkpoint['requests'])
        self.outbox = list(checkpoint['outbox'])
        self.oauth.generation = checkpoint['generation']
        self.oauth.attempt = checkpoint['attempt']
        self.oauth.refresh = checkpoint['refresh']
        if self.oauth.refresh is not None:
            self.oauth.refresh.clear()
            self.oauth.refresh.update(checkpoint['refresh_state'])

    def complete_request(self, request_id, response):
        pending = self.requests.pop(request_id, None)
        if not pending:
            return
        _, completed, failed, valid = pending
        try:
            valid()
            # Reuse the native response boundary, including body size/status checks.
            self.http = lambda *args: response
            checked = self._request('POST', '', {}, '', request_id, 0)
            completed(checked)
        except Exception as error:
            failed(error)
        finally:
            self.http = None

    def fail_request(self, request_id, error):
        pending = self.requests.pop(request_id, None)
        if pending:
            pending[2](ValueError('浏览器网络请求失败，请检查地址、网络和服务的跨域许可；本次结果未保存'))

    def _check_job(self, job):
        if job['_cancel'].is_set() or job['_done'].is_set():
            raise ValueError('模型任务已取消')
        self._match_snapshot(self.profiles.snapshot(), job['profile_id'], job['profile_revision'])
        if job['auth_mode'] == 'codex':
            value = self.oauth._read()
            if (self.oauth.generation != job['_auth_generation'] or self.oauth.session() != job['_auth_session']
                    or not value or value['accountId'] != job['_account']):
                raise ValueError('Codex授权已变化，请重新发送')
        context = job.get('consultation_context')
        if context:
            with closing(storage.connect(self.data_dir)) as conn:
                if core.task_warnings(conn, context):
                    raise ValueError('问诊或书证已变化，请重新发送')

    def _job_failed(self, job, error):
        if job['_done'].is_set():
            return
        job.update(status='cancelled' if job['_cancel'].is_set() else 'failed', validated=False)
        if not job['_cancel'].is_set():
            job['error'] = str(error)[:500] if isinstance(error, (ValueError, DomainError)) else '本机模型通道未完成，本次结果未保存'
        job['_done'].set()

    def _launch_job(self, job, cfg, key, account, request_input, system, context, analysis, allowed):
        job['_account'] = account
        job['_auth_session'] = self.oauth.session()
        def queue_model(access, account_id):
            self._check_job(job)
            method, url, headers, body, _, timeout = self._model_request(job, cfg, access, account_id, request_input, system)
            def valid():
                self._check_job(job)
                job['status'] = 'running'
            def completed(response):
                self._check_job(job)
                text, usage = self._parse_model_response(job, cfg, response)
                self._finish_job(job, cfg, text, usage, context, analysis, allowed)
                job['_done'].set()
            self._queue_request(method, url, headers, body, timeout, completed,
                                lambda error: self._job_failed(job, error), valid)
        try:
            if cfg['auth_mode'] == 'codex':
                self.oauth.ensure_access(job, queue_model, lambda error: self._job_failed(job, error))
            else:
                queue_model(key, account)
        except Exception as error:
            self._job_failed(job, error)
