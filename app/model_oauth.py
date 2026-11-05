"""App-owned Codex OAuth; no other application's authentication store is read."""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from typing import Literal

from .secrets import read_secret, write_secret

ROOT = Path(__file__).resolve().parents[1]
CODEX_BASE = 'https://chatgpt.com/backend-api'


def validate_credential(value):
    if not isinstance(value, dict) or value.get('type') != 'oauth':
        raise ValueError('Codex授权格式无效')
    for key in ('access', 'refresh'):
        token = value.get(key)
        if not isinstance(token, str) or not token or len(token) > 7000 or any(ord(c) <= 32 or ord(c) == 127 for c in token):
            raise ValueError('Codex授权格式无效')
    expiry = value.get('expires')
    if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry) or expiry <= 0:
        raise ValueError('Codex授权有效期无效')
    if not isinstance(value.get('accountId'), str) or not 1 <= len(value['accountId']) <= 256:
        raise ValueError('Codex授权账户信息无效')
    return {key: value[key] for key in ('type', 'access', 'refresh', 'expires', 'accountId')}


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    method: Literal['device', 'browser'] = 'device'


class OAuthManager:
    def __init__(self, data_dir):
        self.path = data_dir / 'codex-secret.dpapi'
        self.state_lock = threading.Lock()
        self.credential_lock = threading.Lock()
        self.generation = 0
        self.attempt = None

    def _read(self):
        raw = read_secret(self.path)
        if not raw:
            return None
        try:
            return validate_credential(json.loads(raw))
        except (ValueError, TypeError):
            raise ValueError('Codex授权已损坏，请重新登录') from None

    def save_credential(self, value):
        write_secret(self.path, json.dumps(validate_credential(value), separators=(',', ':')))

    def status(self):
        with self.credential_lock:
            credential = self._read()
            info = {'logged_in': credential is not None,
                    'expires_at': credential['expires'] / 1000 if credential else None,
                    'requires_refresh': bool(credential and credential['expires'] <= time.time() * 1000 + 60000)}
        with self.state_lock:
            info['login'] = {key: deepcopy(self.attempt[key]) for key in ('id', 'status', 'method', 'auth_url', 'device_code', 'error') if self.attempt and key in self.attempt} if self.attempt else None
        return info

    def _spawn(self):
        node = shutil.which('node')
        script = ROOT / 'ai-bridge/oauth.mjs'
        if not node or not script.is_file():
            raise ValueError('OAuth桥未安装，请先完成模型桥依赖安装')
        env = {k: os.environ[k] for k in ('SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP') if k in os.environ}
        return subprocess.Popen([node, str(script)], cwd=script.parent, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', env=env,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def start(self, method):
        if method not in ('device', 'browser'):
            raise ValueError('不支持的Codex登录方式')
        with self.state_lock:
            if self.attempt and self.attempt['status'] == 'pending':
                raise HTTPException(409, '已有Codex授权等待完成，请先完成或取消')
            self.generation += 1
            attempt = {'id': str(uuid4()), 'status': 'pending', 'method': method, 'generation': self.generation}
            self.attempt = attempt
        threading.Thread(target=self._login, args=(attempt,), daemon=True).start()
        return {'id': attempt['id'], 'status': 'pending', 'method': method}

    def _login(self, attempt):
        process = None
        timer = None
        credential = None
        try:
            process = self._spawn()
            with self.state_lock:
                if self.attempt is not attempt or attempt['status'] != 'pending':
                    return
                attempt['process'] = process
            process.stdin.write(json.dumps({'op': 'login', 'method': attempt['method']}) + '\n')
            process.stdin.flush()
            timer = threading.Timer(905, process.kill)
            timer.daemon = True; timer.start()
            for line in process.stdout:
                if len(line.encode()) > 65536:
                    raise ValueError('授权事件超出大小限制')
                event = json.loads(line)
                if event.get('type') == 'credential':
                    if credential is not None:
                        raise ValueError('授权终态重复')
                    credential = validate_credential(event.get('credential'))
                elif event.get('type') == 'error':
                    raise ValueError('OpenAI授权未完成，请核对网络或改用另一种登录方式')
                elif event.get('type') in ('auth_url', 'device_code', 'progress', 'waiting_callback'):
                    with self.state_lock:
                        if attempt['status'] != 'pending':
                            continue
                        if event['type'] == 'auth_url':
                            from urllib.parse import urlparse
                            parsed = urlparse(event.get('url', ''))
                            if parsed.scheme != 'https' or parsed.hostname not in ('auth.openai.com', 'chatgpt.com') or parsed.username or parsed.password or parsed.port:
                                raise ValueError('非预期的授权地址')
                            attempt['auth_url'] = event['url']
                        elif event['type'] == 'device_code':
                            uri = event.get('verificationUri')
                            if uri != 'https://auth.openai.com/codex/device' or not isinstance(event.get('userCode'), str) or len(event['userCode']) > 64:
                                raise ValueError('设备码响应无效')
                            attempt['device_code'] = {'url': uri, 'code': event['userCode']}
                else:
                    raise ValueError('不支持的授权事件')
            process.wait(timeout=3)
            if process.returncode != 0 or credential is None:
                raise ValueError('OpenAI授权中断，未保存新登录态')
            with self.credential_lock, self.state_lock:
                if self.attempt is attempt and attempt['status'] == 'pending' and attempt['generation'] == self.generation:
                    self.save_credential(credential)
                    attempt['status'] = 'completed'
                    attempt.pop('auth_url', None); attempt.pop('device_code', None)
        except Exception:
            with self.state_lock:
                if attempt['status'] == 'pending':
                    attempt.update(status='failed', error='OpenAI授权未完成；可重试、取消或切换设备码／浏览器登录')
                    attempt.pop('auth_url', None); attempt.pop('device_code', None)
        finally:
            if timer:
                timer.cancel()
            if process:
                if process.poll() is None:
                    process.kill()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
                for stream in (process.stdin, process.stdout):
                    if stream:
                        stream.close()
            with self.state_lock:
                attempt.pop('process', None)

    def cancel(self, attempt_id):
        with self.state_lock:
            if not self.attempt or self.attempt['id'] != attempt_id:
                raise HTTPException(404, '授权请求不存在')
            attempt = self.attempt
            if attempt['status'] != 'pending':
                return {'status': attempt['status']}
            self.generation += 1
            attempt['status'] = 'cancelled'
            attempt.pop('auth_url', None); attempt.pop('device_code', None)
            process = attempt.get('process')
        if process and process.poll() is None:
            process.kill()
        return {'status': 'cancelled'}

    def logout(self):
        with self.state_lock:
            pending = self.attempt['id'] if self.attempt and self.attempt['status'] == 'pending' else None
        if pending:
            self.cancel(pending)
        with self.state_lock:
            self.generation += 1
        with self.credential_lock:
            self.path.unlink(missing_ok=True)

    def _refresh(self, credential):
        process = self._spawn()
        timer = threading.Timer(35, process.kill)
        timer.daemon = True
        timer.start()
        try:
            process.stdin.write(json.dumps({'op': 'refresh', 'credential': credential}) + '\n')
            process.stdin.flush()
            lines = []
            size = 0
            for line in process.stdout:
                size += len(line.encode())
                if size > 65536:
                    raise ValueError()
                lines.append(json.loads(line))
            process.wait(timeout=3)
            if process.returncode != 0 or len(lines) != 1 or lines[0].get('type') != 'credential':
                raise ValueError()
            return validate_credential(lines[0]['credential'])
        except Exception:
            raise ValueError('Codex授权续期失败，请重新登录或稍后重试') from None
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill(); process.wait(timeout=3)
            for stream in (process.stdin, process.stdout):
                if stream and hasattr(stream, 'close'):
                    stream.close()

    def access_token(self):
        with self.credential_lock:
            credential = self._read()
            if credential is None:
                raise HTTPException(409, '请先使用Codex登录')
            if credential['expires'] <= time.time() * 1000 + 60000:
                with self.state_lock:
                    generation = self.generation
                updated = self._refresh(credential)
                with self.state_lock:
                    if generation != self.generation or not self.path.exists():
                        raise ValueError('Codex授权已改变，请重新发起请求')
                    self.save_credential(updated)
                credential = updated
            return credential['access']
