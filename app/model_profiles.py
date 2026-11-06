"""Named model configuration profiles with atomic, secret-free storage."""
import json
import os
from pathlib import Path
import tempfile
import threading
from uuid import uuid4

from fastapi import HTTPException

from .model_oauth import CODEX_BASE
from .secrets import read_secret, write_secret

DEFAULT_CONFIG = {"auth_mode": "api_key", "base_url": "", "model": "", "enabled": False, "allow_external": False, "allow_evidence": False}
PROFILE_FIELDS = ("auth_mode", "base_url", "model", "enabled", "allow_external", "allow_evidence")
MAX_PROFILES = 50
LEGACY_ID = "legacy"
LEGACY_NAME = "原有配置"


def _valid_hex32(value):
    return isinstance(value, str) and len(value) == 32 and all(char in "0123456789abcdef" for char in value)


def valid_profile_id(value):
    # Only exact lowercase uuid hex or the legacy id: hyphenated/uppercase UUIDs can alias Windows key paths.
    return value == LEGACY_ID or _valid_hex32(value)


def _name(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80:
        raise ValueError("配置名称须为1到80个字符")
    return value.strip()


class ProfileStore:
    def __init__(self, data_dir, url_validator=None):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "model-profiles.json"
        self.legacy_config_path = self.data_dir / "model-config.json"
        self.legacy_key_path = self.data_dir / "model-secret.dpapi"
        self.key_dir = self.data_dir / "model-keys"
        self.url_validator = url_validator
        self.lock = threading.RLock()

    @staticmethod
    def _empty():
        return {"version": 1, "revision": 0, "active_id": None, "items": []}

    def _item(self, value):
        required = {"id", "name", *PROFILE_FIELDS}
        if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {"key_ref"}:
            raise ValueError("模型配置档案损坏，请重新保存配置")
        if not valid_profile_id(value["id"]):
            raise ValueError("模型配置档案损坏，请重新保存配置")
        name = _name(value["name"])
        auth_mode = value["auth_mode"]
        if auth_mode not in ("api_key", "codex"):
            raise ValueError("模型配置档案损坏，请重新保存配置")
        base_url = value["base_url"]
        model = value["model"]
        if not isinstance(base_url, str) or len(base_url) > 2048:
            raise ValueError("模型配置档案损坏，请重新保存配置")
        if auth_mode == "codex" and base_url != CODEX_BASE:
            raise ValueError("模型配置档案损坏，请重新保存配置")
        if auth_mode == "api_key" and base_url and self.url_validator:
            try:
                self.url_validator(base_url)
            except (TypeError, ValueError):
                raise ValueError("模型配置档案损坏，请重新保存配置") from None
        if not isinstance(model, str) or len(model) > 200:
            raise ValueError("模型配置档案损坏，请重新保存配置")
        for key in ("enabled", "allow_external", "allow_evidence"):
            if not isinstance(value[key], bool):
                raise ValueError("模型配置档案损坏，请重新保存配置")
        item = {"id": value["id"], "name": name, **{key: value[key] for key in PROFILE_FIELDS}}
        key_ref = value.get("key_ref")
        if key_ref is not None:
            if not _valid_hex32(key_ref):
                raise ValueError("模型配置档案损坏，请重新保存配置")
            item["key_ref"] = key_ref
        return item

    def _checked(self, value):
        if (not isinstance(value, dict) or set(value) != {"version", "revision", "active_id", "items"}
                or type(value["version"]) is not int or value["version"] != 1):
            raise ValueError("模型配置档案损坏，请重新保存配置")
        revision = value["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("模型配置档案损坏，请重新保存配置")
        items = value["items"]
        if not isinstance(items, list) or len(items) > MAX_PROFILES:
            raise ValueError("模型配置档案损坏，请重新保存配置")
        seen, cleaned = set(), []
        for raw in items:
            item = self._item(raw)
            if item["id"] in seen:
                raise ValueError("模型配置档案损坏，请重新保存配置")
            seen.add(item["id"])
            cleaned.append(item)
        active = value["active_id"]
        if active is not None and (not valid_profile_id(active) or active not in seen):
            raise ValueError("模型配置档案损坏，请重新保存配置")
        return {"version": 1, "revision": revision, "active_id": active, "items": cleaned}

    def _read(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            raise ValueError("模型配置档案损坏，请重新保存配置") from exc
        return self._checked(value)

    def _write(self, registry):
        registry = {**registry, "version": 1, "revision": registry["revision"] + 1}
        text = json.dumps(registry, ensure_ascii=False, sort_keys=True, allow_nan=False)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self.data_dir, prefix=".model-profiles-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return registry

    def _legacy_item(self):
        try:
            value = json.loads(self.legacy_config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            raise ValueError("模型配置损坏，请重新保存配置") from exc
        if not isinstance(value, dict):
            raise ValueError("模型配置损坏，请重新保存配置")
        auth_mode = value.get("auth_mode", "api_key")
        if auth_mode not in ("api_key", "codex"):
            raise ValueError("模型配置损坏，请重新保存配置")
        item = {"id": LEGACY_ID, "name": LEGACY_NAME,
                "auth_mode": auth_mode,
                "base_url": CODEX_BASE if auth_mode == "codex" else value.get("base_url", ""),
                "model": value.get("model", ""),
                # Keep the stored value verbatim: _item rejects non-bool flags instead of coercing "false" to True.
                **{key: value.get(key, DEFAULT_CONFIG[key]) for key in ("enabled", "allow_external", "allow_evidence")}}
        return self._item(item)

    def _load(self):
        if self.path.exists():
            return self._read()
        if self.legacy_config_path.exists():
            registry = self._empty()
            registry["items"] = [self._legacy_item()]
            registry["active_id"] = LEGACY_ID
            return self._write(registry)
        return self._empty()

    def snapshot(self):
        with self.lock:
            registry = self._load()
            return {"version": 1, "revision": registry["revision"], "active_id": registry["active_id"],
                    "items": [dict(item) for item in registry["items"]]}

    def _public(self, item):
        # key_ref is private routing metadata and must never leave the store via the API.
        return {"id": item["id"], "name": item["name"], **{key: item[key] for key in PROFILE_FIELDS},
                "has_key": self._item_key_path(item).exists()}

    def list(self):
        snapshot = self.snapshot()
        return {"items": [self._public(item) for item in snapshot["items"]], "active_id": snapshot["active_id"]}

    def _find(self, registry, profile_id):
        if not valid_profile_id(profile_id):
            raise HTTPException(400, "模型配置ID无效")
        index = next((i for i, item in enumerate(registry["items"]) if item["id"] == profile_id), None)
        if index is None:
            raise HTTPException(404, "模型配置不存在")
        return index

    def _prepare(self, fields):
        auth_mode = fields.get("auth_mode", "api_key")
        if auth_mode not in ("api_key", "codex"):
            raise ValueError("模型通道配置无效")
        if auth_mode == "codex":
            base_url = CODEX_BASE
        else:
            base_url = fields.get("base_url", "")
            base_url = self.url_validator(base_url) if self.url_validator else base_url
        model = fields.get("model", "")
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise ValueError("模型ID不能为空")
        for key in ("enabled", "allow_external", "allow_evidence"):
            if not isinstance(fields.get(key, False), bool):
                raise ValueError("模型配置字段无效")
        return {"auth_mode": auth_mode, "base_url": base_url, "model": model,
                **{key: fields.get(key, False) for key in ("enabled", "allow_external", "allow_evidence")}}

    def _key_ref_path(self, profile_id, key_ref):
        return self.key_dir / f"{profile_id}-{key_ref}.dpapi"

    def _item_key_path(self, item):
        key_ref = item.get("key_ref")
        if key_ref:
            return self._key_ref_path(item["id"], key_ref)
        if item["id"] == LEGACY_ID:
            return self.legacy_key_path
        return self.key_dir / f"{item['id']}.dpapi"

    def key_path(self, profile_id):
        with self.lock:
            registry = self._load()
            index = self._find(registry, profile_id)
            return self._item_key_path(registry["items"][index])

    def has_key(self, profile_id):
        return self.key_path(profile_id).exists()

    def read_key(self, profile_id):
        return read_secret(self.key_path(profile_id))

    @staticmethod
    def _discard(path):
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def _stage_key(self, profile_id, api_key):
        key_ref = uuid4().hex
        path = self._key_ref_path(profile_id, key_ref)
        try:
            write_secret(path, api_key)
        except Exception:
            self._discard(path)
            raise
        return key_ref, path

    def create(self, fields, name, api_key=None, activate=False):
        name = _name(name)
        prepared = self._prepare(fields)
        if prepared["auth_mode"] == "codex" and api_key:
            raise ValueError("Codex通道使用网页登录，不接收手动API Key")
        with self.lock:
            registry = self._load()
            if len(registry["items"]) >= MAX_PROFILES:
                raise HTTPException(409, "模型配置数量已达上限")
            profile_id = uuid4().hex
            item = {"id": profile_id, "name": name, **prepared}
            staged = None
            if api_key:
                item["key_ref"], staged = self._stage_key(profile_id, api_key)
            registry["items"].append(item)
            if activate:
                registry["active_id"] = profile_id
            try:
                self._write(registry)
            except Exception:
                # Registry did not commit: drop the unreferenced staged blob so no key outlives its item.
                if staged:
                    self._discard(staged)
                raise
            return self._public(item)

    def update(self, profile_id, fields, name, api_key=None):
        name = _name(name)
        prepared = self._prepare(fields)
        if prepared["auth_mode"] == "codex" and api_key:
            raise ValueError("Codex通道使用网页登录，不接收手动API Key")
        with self.lock:
            registry = self._load()
            index = self._find(registry, profile_id)
            old = registry["items"][index]
            old_path = self._item_key_path(old)
            if (not api_key and prepared['auth_mode'] == 'api_key' and old_path.exists()
                    and (old['auth_mode'] != 'api_key' or old['base_url'] != prepared['base_url'])):
                raise HTTPException(409, '更换API地址或从Codex切回API时，请重新输入对应密钥')
            item = {"id": profile_id, "name": name, **prepared}
            staged = None
            if api_key:
                # Stage a new immutable key blob first; the registry only references it after commit.
                item["key_ref"], staged = self._stage_key(profile_id, api_key)
            elif old.get("key_ref"):
                item["key_ref"] = old["key_ref"]
            registry["items"][index] = item
            try:
                self._write(registry)
            except Exception:
                if staged:
                    self._discard(staged)
                raise
            if staged and old_path != staged:
                self._discard(old_path)
            return self._public(item)

    def select(self, profile_id):
        with self.lock:
            registry = self._load()
            index = self._find(registry, profile_id)
            registry["active_id"] = profile_id
            self._write(registry)
            return self._public(registry["items"][index])

    def delete(self, profile_id):
        with self.lock:
            registry = self._load()
            index = self._find(registry, profile_id)
            item = registry["items"][index]
            current_key = self._item_key_path(item)
            del registry["items"][index]
            if registry["active_id"] == profile_id:
                registry["active_id"] = None
            registry = self._write(registry)
            paths = {current_key}
            if profile_id == LEGACY_ID: paths.add(self.legacy_key_path)
            incomplete = False
            try:
                owned = list(self.key_dir.glob(f"{profile_id}-*.dpapi"))
            except OSError:
                owned = []
                incomplete = True
            for path in owned:
                if _valid_hex32(path.name[len(profile_id) + 1:-len(".dpapi")]):
                    paths.add(path)
            for path in paths:
                if not self._discard(path): incomplete = True
            return {"deleted_id": profile_id, "active_id": registry["active_id"],
                    **({"key_cleanup_incomplete": True} if incomplete else {})}
