"""Single-owner application access, independent of medical rules and model accounts."""
from collections import deque
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import threading
import time

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

ITERATIONS = 600000
SESSION_SECONDS = 8 * 60 * 60


def loopback(request):
    try:
        address = ipaddress.ip_address(request.client.host)
        return address.is_loopback or bool(getattr(address, 'ipv4_mapped', None) and address.ipv4_mapped.is_loopback)
    except (ValueError, AttributeError):
        return False


def lan_hosts(values):
    if not isinstance(values, (list, tuple)) or len(values) > 20:
        raise ValueError('局域网地址列表无效')
    ranges = [ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
    output = []
    for value in values:
        address = ipaddress.ip_address(value)
        if not any(address in network for network in ranges):
            raise ValueError('仅允许明确的局域网IPv4地址')
        output.append(str(address))
    return list(dict.fromkeys(output))


class Password(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: str = Field(min_length=1, max_length=256)


class SetupPassword(Password):
    password: str = Field(min_length=12, max_length=256)


class AccessGate:
    def __init__(self, data_dir):
        self.path = data_dir / 'access.json'
        self.lock = threading.Lock()
        self.attempts = {}
        self.grants = {}
        self.hash_slots = threading.BoundedSemaphore(2)

    @property
    def configured(self):
        return self.path.exists()

    def authenticated(self, token):
        with self.lock:
            return self.grants.get(token, 0) > time.monotonic()

    def grant(self, token):
        with self.lock:
            now = time.monotonic()
            self.grants = {k: v for k, v in self.grants.items() if v > now}
            self.grants[token] = now + SESSION_SECONDS

    def revoke(self, token):
        with self.lock:
            self.grants.pop(token, None)

    def transport(self, request):
        if not loopback(request) and request.url.scheme != 'https':
            raise HTTPException(403, '局域网访问需要HTTPS连接')

    def require(self, request, token):
        self.transport(request)
        if not self.configured:
            if not loopback(request):
                raise HTTPException(403, '请先在电脑本机设置局域网访问密码')
        elif not self.authenticated(token):
            raise HTTPException(401, '请先登录工作台')

    def setup(self, request, password):
        if not loopback(request):
            raise HTTPException(403, '首次设置只能在运行工作台的电脑本机完成')
        with self.lock:
            if self.configured:
                raise HTTPException(409, '访问密码已经设置')
            salt = secrets.token_hex(16)
            digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
            temporary = self.path.with_suffix('.tmp')
            with temporary.open('w', encoding='utf-8') as f:
                json.dump({'version': 1, 'salt': salt, 'hash': digest, 'iterations': ITERATIONS}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.path)
            self.grants.clear()

    def login(self, request, password):
        self.transport(request)
        if not self.configured:
            raise HTTPException(409, '请先在电脑本机设置访问密码')
        peer = request.client.host if request.client else 'unknown'
        with self.lock:
            now = time.monotonic()
            self.attempts = {k: v for k, v in self.attempts.items() if v and v[-1] > now - 900}
            if len(self.attempts) >= 1024 and peer not in self.attempts:
                raise HTTPException(429, '登录请求过多，请稍后再试')
            recent = self.attempts.setdefault(peer, deque())
            while recent and recent[0] <= now - 900:
                recent.popleft()
            if len(recent) >= 5:
                raise HTTPException(429, '登录尝试过多，请15分钟后重试')
            recent.append(now)
        if not self.hash_slots.acquire(blocking=False):
            raise HTTPException(429, '登录请求繁忙，请稍后重试')
        try:
            try:
                value = json.loads(self.path.read_text(encoding='utf-8'))
                if value.get('version') != 1 or value.get('iterations') != ITERATIONS:
                    raise ValueError()
                salt = bytes.fromhex(value['salt'])
                expected = bytes.fromhex(value['hash'])
                if len(salt) != 16 or len(expected) != 32:
                    raise ValueError()
            except (ValueError, KeyError, OSError, TypeError):
                raise ValueError('访问配置损坏，请在电脑本机恢复') from None
            actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)
            if not hmac.compare_digest(expected, actual):
                raise HTTPException(401, '访问密码不正确')
            with self.lock:
                self.attempts.pop(peer, None)
        finally:
            self.hash_slots.release()
