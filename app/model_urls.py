"""Model endpoint validation shared by desktop and native mobile transports."""
from urllib.parse import urlparse

CODEX_BASE = 'https://chatgpt.com/backend-api'


def validate_url(url):
    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() for c in url):
        raise ValueError("模型地址格式无效")
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("模型地址或端口无效") from exc
    local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ValueError("远端模型需要HTTPS，HTTP仅允许明确的本机回环地址")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError("地址不得包含账号、口令、查询参数或片段")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("模型端口无效")
    return url.rstrip("/")
