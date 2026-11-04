"""Windows current-user DPAPI; no plaintext fallback."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import tempfile


class Blob(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _transform(data: bytes, protect: bool):
    if os.name != "nt":
        raise ValueError("此版本的凭据存储需要Windows DPAPI")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    target = Blob()
    if protect:
        operation = crypt.CryptProtectData
        operation.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        arguments = [ctypes.byref(source), "TCM local model credential", None, None, None, 1, ctypes.byref(target)]
    else:
        operation = crypt.CryptUnprotectData
        operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        arguments = [ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)]
    operation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not operation(*arguments):
        raise ValueError("凭据保护或解密失败，请在原Windows用户下重新配置")
    try:
        return ctypes.string_at(target.data, target.length)
    finally:
        kernel.LocalFree(target.data)


def write_secret(path: Path, secret: str):
    if not isinstance(secret, str) or len(secret) > 16384:
        raise ValueError("无效的凭据长度")
    encrypted = _transform(secret.encode("utf-8"), True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        handle.write(encrypted)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_secret(path: Path):
    if not path.exists():
        return ""
    return _transform(path.read_bytes(), False).decode("utf-8")
