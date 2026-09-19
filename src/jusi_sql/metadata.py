from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Mapping

from .completion import MetadataSnapshot


DEFAULT_METADATA_TTL = 60 * 60.0
_SECRET_MARKERS = ("password", "passphrase", "secret", "token", "api_key", "private_key", "sslkey", "krb5ccname")


class MetadataCache:
    """Thread-safe stale-while-refresh cache shared by SQL providers."""

    def __init__(
        self,
        cache_directory: Path,
        loader: Callable[[], MetadataSnapshot],
        *,
        ttl: float = DEFAULT_METADATA_TTL,
        on_warning: Callable[[str], None] | None = None,
    ) -> None:
        self.path = Path(cache_directory) / "metadata.json"
        self.loader = loader
        self.ttl = max(0.0, float(ttl))
        self.on_warning = on_warning
        self._lock = threading.Lock()
        self._refreshing = False
        self._thread: threading.Thread | None = None
        self._snapshot = MetadataSnapshot.from_dict(_read_json(self.path))

    def snapshot(self) -> MetadataSnapshot:
        with self._lock:
            return MetadataSnapshot.from_dict(self._snapshot.to_dict())

    def mark_stale(self) -> None:
        with self._lock:
            self._snapshot.refreshed_at = 0.0

    def ensure_fresh_async(self, *, force: bool = False) -> bool:
        with self._lock:
            age = time.time() - self._snapshot.refreshed_at if self._snapshot.refreshed_at else float("inf")
            if self._refreshing or (not force and age < self.ttl):
                return False
            self._refreshing = True
            self._thread = threading.Thread(target=self._refresh, name="jusi-sql-metadata", daemon=True)
            self._thread.start()
            return True

    def close(self, *, timeout: float = 2.0) -> bool:
        with self._lock:
            thread = self._thread
        if thread is None or not thread.is_alive():
            return True
        thread.join(timeout=max(0.0, timeout))
        return not thread.is_alive()

    def _refresh(self) -> None:
        try:
            snapshot = self.loader()
            if not isinstance(snapshot, MetadataSnapshot):
                raise TypeError("metadata loader must return MetadataSnapshot")
            snapshot.refreshed_at = time.time()
            _write_json(self.path, snapshot.to_dict())
            with self._lock:
                self._snapshot = snapshot
        except Exception as exc:
            if self.on_warning is not None:
                self.on_warning(f"SQL metadata refresh failed: {exc.__class__.__name__}: {exc}")
        finally:
            with self._lock:
                self._refreshing = False


def sql_cache_directory(
    provider_id: str,
    alias: str,
    options: Mapping[str, Any],
    *,
    state_home: Path | None = None,
) -> Path:
    """Return a stable cache path whose fingerprint never includes secret values."""
    root = state_home or _default_state_home()
    redacted = _redact_secrets(options)
    encoded = json.dumps(redacted, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return root / "plugins" / _safe_segment(provider_id) / _safe_segment(alias) / digest


def _default_state_home() -> Path:
    override = os.environ.get("JUSI_STATE_HOME", "").strip()
    if override:
        return Path(os.path.expanduser(override)).resolve()
    xdg_state = os.environ.get("XDG_STATE_HOME", "").strip()
    if xdg_state:
        return (Path(os.path.expanduser(xdg_state)) / "jusi").resolve()
    return (Path.home() / ".local" / "state" / "jusi").resolve()


def _redact_secrets(value: Any, *, key: str = "") -> Any:
    lowered = key.lower().replace("-", "_")
    if any(marker in lowered for marker in _SECRET_MARKERS):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {str(item_key): _redact_secrets(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_secrets(item) for item in value]
    return deepcopy(value)


def _safe_segment(value: object) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-._")
    return normalized[:120] or "default"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(dict(payload), stream, ensure_ascii=True, sort_keys=True)
            stream.write("\n")
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
