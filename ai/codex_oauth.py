"""OpenAI Codex (ChatGPT subscription) OAuth manager using official Device Code & PKCE flows.

Stores app-owned OAuth credentials cleanly in `<data_dir>/codex_oauth.json` with 0600 permissions,
supports automatic token refresh, and never reads external applications' credential stores.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import uuid4

import httpx

AUTH_BASE = "https://auth.openai.com"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEVICE_URI = f"{AUTH_BASE}/codex/device"
DEVICE_USERCODE_URL = f"{AUTH_BASE}/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = f"{AUTH_BASE}/api/accounts/deviceauth/token"
TOKEN_URL = f"{AUTH_BASE}/oauth/token"
AUTHORIZE_URL = f"{AUTH_BASE}/oauth/authorize"
DEVICE_REDIRECT_URI = f"{AUTH_BASE}/deviceauth/callback"
BROWSER_REDIRECT_PORT = 1455
BROWSER_REDIRECT_URI = f"http://localhost:{BROWSER_REDIRECT_PORT}/auth/callback"

CREDENTIAL_FILENAME = "codex_oauth.json"
LOGIN_TIMEOUT_SEC = 900.0
REFRESH_BUFFER_MS = 60_000


class CodexOAuthError(RuntimeError):
    """Sanitized OAuth error safe for UI display."""


def credential_path(data_dir: Path) -> Path:
    return Path(data_dir).resolve() / CREDENTIAL_FILENAME


def mask_account_label(account_id: str, email: str = "") -> str:
    clean_email = (email or "").strip()
    if clean_email and "@" in clean_email:
        local, domain = clean_email.split("@", 1)
        head = local[:2] if len(local) > 2 else local[:1]
        return f"{head}***@{domain}"
    acc = (account_id or "").strip()
    if not acc:
        return ""
    if len(acc) <= 10:
        return f"{acc[:2]}***"
    return f"{acc[:6]}...{acc[-4:]}"


def _decode_jwt_payload(jwt_token: str) -> dict[str, Any]:
    parts = (jwt_token or "").split(".")
    if len(parts) < 2:
        raise ValueError("JWT 格式无效")
    seg = parts[1]
    padded = seg + "=" * (-len(seg) % 4)
    decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    obj = json.loads(decoded)
    if not isinstance(obj, dict):
        raise ValueError("JWT 载荷无效")
    return obj


def _extract_auth_claims(token_payload: dict[str, Any], *, fallback_account: str = "") -> tuple[str, str, str]:
    access_token = str(token_payload.get("access_token") or "")
    claims = _decode_jwt_payload(access_token)
    auth_ns = claims.get("https://api.openai.com/auth")
    account_id = ""
    plan_type = ""
    if isinstance(auth_ns, dict):
        account_id = str(auth_ns.get("chatgpt_account_id") or "").strip()
        plan_type = str(auth_ns.get("chatgpt_plan_type") or "").strip()
    if not account_id:
        account_id = str(claims.get("sub") or fallback_account or "").strip()
    if not account_id:
        raise ValueError("OpenAI 授权令牌中缺少 chatgpt_account_id")

    email = ""
    id_token = str(token_payload.get("id_token") or "").strip()
    if id_token:
        try:
            id_claims = _decode_jwt_payload(id_token)
            email = str(id_claims.get("email") or "").strip()
        except Exception:
            email = ""
    if not email:
        profile_ns = claims.get("https://api.openai.com/profile")
        if isinstance(profile_ns, dict):
            email = str(profile_ns.get("email") or "").strip()
    return account_id, plan_type, email


def validate_credential(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("type") != "oauth":
        raise ValueError("Codex 授权格式无效")
    access = str(raw.get("access") or "").strip()
    refresh = str(raw.get("refresh") or "").strip()
    account_id = str(raw.get("account_id") or raw.get("accountId") or "").strip()
    expires = raw.get("expires")
    if not access or not refresh or len(access) > 16384 or len(refresh) > 16384:
        raise ValueError("Codex 授权令牌缺失或长度无效")
    if not account_id or len(account_id) > 256:
        raise ValueError("Codex 账户标识无效")
    if isinstance(expires, bool) or not isinstance(expires, (int, float)) or expires <= 0:
        raise ValueError("Codex 授权有效期无效")
    return {
        "type": "oauth",
        "access": access,
        "refresh": refresh,
        "expires": float(expires),
        "account_id": account_id,
        "plan_type": str(raw.get("plan_type") or "").strip()[:48],
        "email": str(raw.get("email") or "").strip()[:120],
        "updated_at": float(raw.get("updated_at") or time.time()),
    }


def _credential_from_token_response(
    token_data: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(token_data, dict):
        raise CodexOAuthError("OpenAI 返回的授权响应格式无效")
    access = str(token_data.get("access_token") or "").strip()
    refresh = str(token_data.get("refresh_token") or (previous or {}).get("refresh") or "").strip()
    expires_in = token_data.get("expires_in")
    if not access or not refresh:
        raise CodexOAuthError("OpenAI 授权响应缺少 access_token 或 refresh_token")
    try:
        expiry_sec = float(expires_in)
    except (TypeError, ValueError) as exc:
        raise CodexOAuthError("OpenAI 授权有效期字段无效") from exc
    if expiry_sec <= 0:
        raise CodexOAuthError("OpenAI 授权有效期字段无效")
    try:
        account_id, plan_type, email = _extract_auth_claims(
            token_data,
            fallback_account=str((previous or {}).get("account_id") or ""),
        )
    except Exception as exc:
        raise CodexOAuthError(f"无法识别 Codex 账户信息：{exc}") from exc

    return validate_credential(
        {
            "type": "oauth",
            "access": access,
            "refresh": refresh,
            "expires": time.time() * 1000.0 + expiry_sec * 1000.0,
            "account_id": account_id,
            "plan_type": plan_type or (previous or {}).get("plan_type") or "",
            "email": email or (previous or {}).get("email") or "",
            "updated_at": time.time(),
        }
    )


def read_credential(data_dir: Path) -> dict[str, Any] | None:
    path = credential_path(data_dir)
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return validate_credential(loaded)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def write_credential(data_dir: Path, cred: dict[str, Any]) -> dict[str, Any]:
    cleaned = validate_credential(cred)
    path = credential_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        temp_path = Path(tmp.name)
        try:
            json.dump(cleaned, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            tmp.close()
            os.replace(temp_path, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        finally:
            temp_path.unlink(missing_ok=True)
    return cleaned


def delete_credential(data_dir: Path) -> None:
    credential_path(data_dir).unlink(missing_ok=True)


def _build_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _build_client(timeout_sec: float = 25.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=15.0, read=timeout_sec, write=15.0, pool=15.0),
        trust_env=True,
        follow_redirects=False,
    )


@dataclass
class _LoginAttempt:
    id: str
    method: str
    status: str = "pending"
    stage: str = "starting"
    user_code: str = ""
    verification_uri: str = DEVICE_URI
    auth_url: str = ""
    device_auth_id: str = ""
    interval_sec: float = 5.0
    code_verifier: str = ""
    state: str = ""
    callback_listening: bool = False
    error: str = ""
    deadline_mono: float = field(default_factory=lambda: time.monotonic() + LOGIN_TIMEOUT_SEC)
    task: asyncio.Task[Any] | None = None
    http_server: ThreadingHTTPServer | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "method": self.method,
            "status": self.status,
            "stage": self.stage,
            "user_code": self.user_code,
            "verification_uri": self.verification_uri,
            "auth_url": self.auth_url,
            "callback_listening": self.callback_listening,
            "error": self.error,
        }


class _ManagerState:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.refresh_lock = asyncio.Lock()
        self.attempt: _LoginAttempt | None = None
        self.generation = 0


_MANAGERS: dict[Path, _ManagerState] = {}
_MANAGERS_GUARD = threading.Lock()


def _manager_for(data_dir: Path) -> _ManagerState:
    key = Path(data_dir).resolve()
    with _MANAGERS_GUARD:
        mgr = _MANAGERS.get(key)
        if mgr is None:
            mgr = _ManagerState(key)
            _MANAGERS[key] = mgr
        return mgr


def _stop_attempt_resources(attempt: _LoginAttempt | None) -> None:
    if not attempt:
        return
    if attempt.task and not attempt.task.done():
        attempt.task.cancel()
    if attempt.http_server is not None:
        srv = attempt.http_server
        attempt.http_server = None
        threading.Thread(target=srv.shutdown, daemon=True).start()
        try:
            srv.server_close()
        except Exception:
            pass


def get_public_status(data_dir: Path) -> dict[str, Any]:
    mgr = _manager_for(data_dir)
    cred = read_credential(mgr.data_dir)
    now_ms = time.time() * 1000.0
    login_info = mgr.attempt.public_dict() if mgr.attempt else None
    return {
        "logged_in": cred is not None,
        "account_masked": mask_account_label(cred["account_id"], cred.get("email", "")) if cred else "",
        "plan_type": cred.get("plan_type", "") if cred else "",
        "expires_at": (cred["expires"] / 1000.0) if cred else None,
        "requires_refresh": bool(cred and cred["expires"] <= now_ms + REFRESH_BUFFER_MS),
        "login": login_info,
    }


async def _exchange_authorization_code(
    data_dir: Path,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    owns_client = client is None
    http = client or _build_client(25.0)
    try:
        resp = await http.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
    except httpx.HTTPError as exc:
        raise CodexOAuthError(f"连接 OpenAI 兑换授权令牌失败：{type(exc).__name__}") from exc
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code >= 400:
        detail = ""
        try:
            err_json = resp.json()
            detail = str(err_json.get("error_description") or err_json.get("error") or "")
        except Exception:
            detail = (resp.text or "").strip()[:160]
        raise CodexOAuthError(f"OpenAI 令牌兑换失败 (HTTP {resp.status_code})：{detail}".strip())

    try:
        token_data = resp.json()
    except Exception as exc:
        raise CodexOAuthError("OpenAI 返回的令牌格式无法解析") from exc

    cred = _credential_from_token_response(token_data)
    write_credential(data_dir, cred)
    return cred


async def _poll_device_login(mgr: _ManagerState, attempt: _LoginAttempt, client: httpx.AsyncClient | None = None) -> None:
    owns_client = client is None
    http = client or _build_client(25.0)
    gen = mgr.generation
    try:
        while time.monotonic() < attempt.deadline_mono:
            if mgr.attempt is not attempt or mgr.generation != gen or attempt.status != "pending":
                return
            await asyncio.sleep(max(1.0, attempt.interval_sec))
            if mgr.attempt is not attempt or mgr.generation != gen or attempt.status != "pending":
                return
            try:
                resp = await http.post(
                    DEVICE_TOKEN_URL,
                    json={
                        "device_auth_id": attempt.device_auth_id,
                        "user_code": attempt.user_code,
                    },
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
            except httpx.HTTPError:
                continue

            if resp.status_code == 200:
                try:
                    grant = resp.json()
                except Exception:
                    grant = {}
                auth_code = str(grant.get("authorization_code") or "").strip()
                verifier = str(grant.get("code_verifier") or "").strip()
                if not auth_code or not verifier:
                    attempt.status = "failed"
                    attempt.stage = "failed"
                    attempt.error = "OpenAI 返回的设备码授权数据不完整，请重新发起。"
                    return
                attempt.stage = "exchanging_token"
                await _exchange_authorization_code(
                    mgr.data_dir,
                    code=auth_code,
                    code_verifier=verifier,
                    redirect_uri=DEVICE_REDIRECT_URI,
                    client=http,
                )
                mgr.generation += 1
                attempt.status = "completed"
                attempt.stage = "completed"
                return

            err_code = ""
            try:
                body = resp.json()
                err = body.get("error") if isinstance(body, dict) else None
                err_code = str(err.get("code") if isinstance(err, dict) else err or "").lower()
            except Exception:
                err_code = ""

            if err_code == "slow_down":
                attempt.interval_sec += 5.0
                continue
            if resp.status_code in (403, 404) or err_code in (
                "authorization_pending",
                "deviceauth_authorization_pending",
            ):
                continue
            attempt.status = "failed"
            attempt.stage = "failed"
            attempt.error = f"OpenAI 设备码授权未通过 (HTTP {resp.status_code})，请重新获取设备码。"
            return

        if attempt.status == "pending":
            attempt.status = "failed"
            attempt.stage = "timeout"
            attempt.error = "设备码授权已超时（15 分钟），请重新发起。"
    except asyncio.CancelledError:
        if attempt.status == "pending":
            attempt.status = "cancelled"
            attempt.stage = "cancelled"
        raise
    except CodexOAuthError as exc:
        attempt.status = "failed"
        attempt.stage = "failed"
        attempt.error = str(exc)
    except Exception as exc:
        attempt.status = "failed"
        attempt.stage = "failed"
        attempt.error = f"设备码轮询异常：{type(exc).__name__}"
    finally:
        if owns_client:
            await http.aclose()


def _start_local_callback_listener(
    mgr: _ManagerState,
    attempt: _LoginAttempt,
    loop: asyncio.AbstractEventLoop,
) -> bool:
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/auth/callback":
                self.send_response(404)
                self.end_headers()
                return
            qs = parse_qs(parsed.query)
            code = (qs.get("code") or [""])[0]
            state = (qs.get("state") or [""])[0]
            err = (qs.get("error") or [""])[0]
            if err:
                attempt.status = "failed"
                attempt.stage = "failed"
                attempt.error = f"OpenAI 网页授权被拒绝：{err}"
                msg = f"<h3>授权未完成：{err}</h3><p>请返回「倪氏经方」工作台查看详情。</p>"
            elif not code or state != attempt.state:
                msg = "<h3>回调参数不匹配或缺少授权码</h3><p>请关闭此页面并在工作台重试。</p>"
            else:
                msg = "<h3>Codex 授权已接收！</h3><p>可以关闭此标签页，返回「倪氏经方」工作台即可看到登录状态。</p>"
                loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(_complete_browser_callback(mgr, attempt, code))
                )
            body_bytes = (
                "<!doctype html><meta charset='utf-8'>"
                "<body style='font-family:sans-serif;padding:24px;background:#f7f4eb;color:#1f2a24'>"
                f"{msg}</body>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    try:
        server = ThreadingHTTPServer(("127.0.0.1", BROWSER_REDIRECT_PORT), CallbackHandler)
    except OSError:
        return False
    attempt.http_server = server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return True


async def _complete_browser_callback(mgr: _ManagerState, attempt: _LoginAttempt, code: str) -> None:
    if mgr.attempt is not attempt or attempt.status != "pending":
        return
    attempt.stage = "exchanging_token"
    try:
        await _exchange_authorization_code(
            mgr.data_dir,
            code=code,
            code_verifier=attempt.code_verifier,
            redirect_uri=BROWSER_REDIRECT_URI,
        )
        mgr.generation += 1
        attempt.status = "completed"
        attempt.stage = "completed"
    except CodexOAuthError as exc:
        attempt.status = "failed"
        attempt.stage = "failed"
        attempt.error = str(exc)
    finally:
        if attempt.http_server is not None:
            srv = attempt.http_server
            attempt.http_server = None
            threading.Thread(target=srv.shutdown, daemon=True).start()


async def start_login(
    data_dir: Path,
    *,
    method: str = "device",
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    clean_method = (method or "device").strip().lower()
    if clean_method not in {"device", "browser"}:
        raise CodexOAuthError("不支持的 Codex 授权方式，请使用 device 或 browser。")

    mgr = _manager_for(data_dir)
    _stop_attempt_resources(mgr.attempt)
    mgr.generation += 1
    attempt = _LoginAttempt(id=uuid4().hex, method=clean_method)
    mgr.attempt = attempt

    if clean_method == "browser":
        verifier, challenge = _build_pkce_pair()
        state = secrets.token_hex(16)
        params = urlencode(
            {
                "response_type": "code",
                "client_id": CLIENT_ID,
                "redirect_uri": BROWSER_REDIRECT_URI,
                "scope": "openid profile email offline_access",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
                "id_token_add_organizations": "true",
                "codex_cli_simplified_flow": "true",
                "originator": "nihaixia-tcm",
            }
        )
        attempt.code_verifier = verifier
        attempt.state = state
        attempt.auth_url = f"{AUTHORIZE_URL}?{params}"
        attempt.stage = "waiting_authorization"
        loop = asyncio.get_running_loop()
        attempt.callback_listening = _start_local_callback_listener(mgr, attempt, loop)
        return get_public_status(data_dir)

    owns_client = client is None
    http = client or _build_client(20.0)
    try:
        try:
            resp = await http.post(
                DEVICE_USERCODE_URL,
                json={"client_id": CLIENT_ID},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
        except httpx.TimeoutException as exc:
            attempt.status = "failed"
            attempt.stage = "failed"
            raise CodexOAuthError("连接 OpenAI 设备码接口超时，请检查网络或代理设置后重试。") from exc
        except httpx.HTTPError as exc:
            attempt.status = "failed"
            attempt.stage = "failed"
            raise CodexOAuthError(f"无法连接 OpenAI 授权服务 ({type(exc).__name__})，请确认网络/代理已开启。") from exc

        if resp.status_code >= 400:
            attempt.status = "failed"
            attempt.stage = "failed"
            raise CodexOAuthError(f"申请 Codex 设备码失败 (HTTP {resp.status_code})，请稍后重试。")

        try:
            device = resp.json()
        except Exception as exc:
            attempt.status = "failed"
            attempt.stage = "failed"
            raise CodexOAuthError("OpenAI 设备码响应格式无效。") from exc

        device_auth_id = str(device.get("device_auth_id") or "").strip()
        user_code = str(device.get("user_code") or "").strip()
        try:
            interval = max(1.0, float(device.get("interval") or 5.0))
        except (TypeError, ValueError):
            interval = 5.0
        if not device_auth_id or not user_code:
            attempt.status = "failed"
            attempt.stage = "failed"
            raise CodexOAuthError("OpenAI 返回的设备码字段不完整。")

        attempt.device_auth_id = device_auth_id
        attempt.user_code = user_code
        attempt.interval_sec = interval
        attempt.stage = "waiting_authorization"
        attempt.auth_url = DEVICE_URI
        if client is None:
            attempt.task = asyncio.create_task(_poll_device_login(mgr, attempt))
        return get_public_status(data_dir)
    finally:
        if owns_client:
            await http.aclose()


async def submit_callback_url(
    data_dir: Path,
    raw_value: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    mgr = _manager_for(data_dir)
    attempt = mgr.attempt
    if not attempt or attempt.method != "browser" or attempt.status != "pending":
        raise CodexOAuthError("当前没有进行中的浏览器授权，请先点击「浏览器授权登录」。")

    raw = (raw_value or "").strip()
    query_str = urlparse(raw).query if "://" in raw else raw.lstrip("?")
    qs = parse_qs(query_str)
    err = (qs.get("error") or [""])[0]
    if err:
        raise CodexOAuthError(f"回调网址中包含授权错误：{err}")
    code = (qs.get("code") or [""])[0].strip()
    state = (qs.get("state") or [""])[0].strip()
    if not code:
        raise CodexOAuthError("回调网址中未找到 code= 参数，请复制完整的 http://localhost:1455/auth/callback?... 地址。")
    if state and state != attempt.state:
        raise CodexOAuthError("回调 state 与当前登录会话不一致，请重新发起浏览器授权。")

    attempt.stage = "exchanging_token"
    await _exchange_authorization_code(
        mgr.data_dir,
        code=code,
        code_verifier=attempt.code_verifier,
        redirect_uri=BROWSER_REDIRECT_URI,
        client=client,
    )
    _stop_attempt_resources(attempt)
    mgr.generation += 1
    attempt.status = "completed"
    attempt.stage = "completed"
    return get_public_status(data_dir)


def cancel_login(data_dir: Path) -> dict[str, Any]:
    mgr = _manager_for(data_dir)
    if mgr.attempt and mgr.attempt.status == "pending":
        mgr.attempt.status = "cancelled"
        mgr.attempt.stage = "cancelled"
    _stop_attempt_resources(mgr.attempt)
    mgr.generation += 1
    return get_public_status(data_dir)


def logout(data_dir: Path) -> dict[str, Any]:
    mgr = _manager_for(data_dir)
    _stop_attempt_resources(mgr.attempt)
    mgr.attempt = None
    mgr.generation += 1
    delete_credential(data_dir)
    return get_public_status(data_dir)


async def ensure_fresh_runtime_config(
    data_dir: Path,
    cfg: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Ensure Codex OAuth token is valid & refreshed cleanly before calling Codex Responses API."""
    if (cfg.get("protocol") or "").strip().lower() != "codex_oauth":
        return cfg

    mgr = _manager_for(data_dir)
    async with mgr.refresh_lock:
        cred = read_credential(mgr.data_dir)
        if not cred:
            raise CodexOAuthError("尚未登录 OpenAI Codex 账号，请在「模型设置」点击设备码或浏览器授权登录。")

        now_ms = time.time() * 1000.0
        if cred["expires"] > now_ms + REFRESH_BUFFER_MS:
            return {
                **cfg,
                "api_key": cred["access"],
                "codex_account_id": cred["account_id"],
                "key_source": "codex_oauth",
                "ready": bool(cfg.get("base_url") and cfg.get("model") and cred["access"]),
            }

        owns_client = client is None
        http = client or _build_client(25.0)
        try:
            resp = await http.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": cred["refresh"],
                    "client_id": CLIENT_ID,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise CodexOAuthError(f"刷新 Codex 授权失败 ({type(exc).__name__})，请检查网络或重新登录。") from exc
        finally:
            if owns_client:
                await http.aclose()

        if resp.status_code >= 400:
            raise CodexOAuthError(f"Codex 授权已过期或被撤销 (HTTP {resp.status_code})，请重新登录 Codex。")
        try:
            refreshed = _credential_from_token_response(resp.json(), previous=cred)
        except CodexOAuthError:
            raise
        except Exception as exc:
            raise CodexOAuthError("刷新 Codex 授权返回格式无效，请重新登录。") from exc

        write_credential(mgr.data_dir, refreshed)
        return {
            **cfg,
            "api_key": refreshed["access"],
            "codex_account_id": refreshed["account_id"],
            "key_source": "codex_oauth",
            "ready": bool(cfg.get("base_url") and cfg.get("model") and refreshed["access"]),
        }
