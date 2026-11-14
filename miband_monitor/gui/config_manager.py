"""Safe configuration reading (redacted) and .env updating for the GUI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from ..ble.identity import _env_device_id, is_placeholder_device_id, normalize_auth_key
from ..config.defaults import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_DATA_DIR,
    DEFAULT_SCAN_TIMEOUT,
    ENV_AUTH_KEY,
    ENV_BAND_TZ,
    ENV_DEMO_MODE,
    ENV_DEVICE_ID,
    ENV_DEVICE_NAME,
    ENV_OUTPUT_DIR,
)
from ..config.demo import DEMO_AUTH_KEY_HEX, DEMO_DEVICE_ID
from ..config.env import load_env, secure_env_file, update_env_file
from ..config.paths import default_env_path
from ..config.privacy import mask_address
from ..history import resolve_band_tz


def get_masked_config(
    *,
    env_path: Optional[Path] = None,
    output_dir: Optional[str] = None,
) -> dict[str, Any]:
    """Return configuration metadata with DEVICE_ID masked and AUTH_KEY omitted."""
    target = Path(env_path) if env_path is not None else default_env_path()
    if target.exists():
        load_env(target)
        secure_env_file(target)

    device_id = _env_device_id()
    device_name = (os.getenv(ENV_DEVICE_NAME) or "").strip()
    auth_key = (os.getenv(ENV_AUTH_KEY) or "").strip()
    band_tz = (os.getenv(ENV_BAND_TZ) or "").strip()
    resolved_out = (output_dir or os.getenv(ENV_OUTPUT_DIR) or DEFAULT_DATA_DIR).strip()

    device_configured = bool(device_id and not is_placeholder_device_id(device_id))
    auth_configured = bool(auth_key and not auth_key.lower().startswith("0123456789abcdef"))
    auth_valid = False
    if auth_key:
        try:
            normalize_auth_key(auth_key)
            auth_valid = True
        except ValueError:
            auth_valid = False

    return {
        "env_exists": target.exists(),
        "device_id_configured": device_configured,
        "device_id_masked": mask_address(device_id) if device_configured else "",
        "device_name": device_name,
        "auth_key_configured": auth_configured,
        "auth_key_valid": auth_valid,
        "band_tz": band_tz,
        "output_dir": resolved_out,
    }


def update_gui_config(
    payload: dict[str, Any],
    *,
    env_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Validate and persist updated device credentials/options to .env (0600).

    Empty fields are left untouched so users can update a single setting without
    re-entering existing secrets. Never echoes AUTH_KEY back in the response.
    """
    target = Path(env_path) if env_path is not None else default_env_path()
    device_id = str(payload.get("device_id") or "").strip()
    auth_key = str(payload.get("auth_key") or "").strip()
    device_name = payload.get("device_name")
    band_tz = payload.get("band_tz")

    if auth_key:
        normalize_auth_key(auth_key)

    if band_tz is not None and str(band_tz).strip():
        resolve_band_tz(str(band_tz).strip())

    if device_id:
        if is_placeholder_device_id(device_id):
            raise ValueError("DEVICE_ID cannot be a placeholder value.")
        update_env_file(target, ENV_DEVICE_ID, device_id)
        os.environ[ENV_DEVICE_ID] = device_id

    if auth_key:
        cleaned = auth_key.lower()
        if cleaned.startswith("0x"):
            cleaned = cleaned[2:]
        update_env_file(target, ENV_AUTH_KEY, cleaned)
        os.environ[ENV_AUTH_KEY] = cleaned

    if device_name is not None:
        cleaned_name = str(device_name).strip()
        update_env_file(target, ENV_DEVICE_NAME, cleaned_name)
        os.environ[ENV_DEVICE_NAME] = cleaned_name

    if band_tz is not None:
        cleaned_tz = str(band_tz).strip()
        update_env_file(target, ENV_BAND_TZ, cleaned_tz)
        os.environ[ENV_BAND_TZ] = cleaned_tz

    secure_env_file(target)
    return get_masked_config(env_path=target)


def resolve_session_options(
    options: Optional[dict[str, Any]],
    *,
    env_path: Optional[Path] = None,
) -> tuple[str, str, dict[str, Any]]:
    """Validate and normalize GUI session launch options and credentials."""
    if env_path is not None and env_path.exists():
        load_env(env_path)
    opts = dict(options or {})
    demo = bool(
        opts.get("demo")
        or os.getenv(ENV_DEMO_MODE, "0").lower() in ("1", "true", "yes", "on")
    )
    sync_sleep_spo2 = bool(opts.get("sync_sleep_spo2", False))
    raw_history = opts.get("sync_history_days")
    sync_history_days = int(raw_history) if raw_history not in (None, "", 0, False) else None
    if sync_sleep_spo2 and sync_history_days is None:
        sync_history_days = 7
    raw_duration = opts.get("duration")
    duration = int(raw_duration) if raw_duration not in (None, "", 0) else None

    device_id = _env_device_id()
    auth_key = (os.getenv(ENV_AUTH_KEY) or "").strip()
    if demo:
        if is_placeholder_device_id(device_id):
            device_id = DEMO_DEVICE_ID
        try:
            normalize_auth_key(auth_key)
        except ValueError:
            auth_key = DEMO_AUTH_KEY_HEX
    else:
        if is_placeholder_device_id(device_id):
            raise ValueError("DEVICE_ID is not configured. Configure it in Settings first.")
        normalize_auth_key(auth_key)

    normalized = {
        "demo": demo,
        "imu": bool(opts.get("imu", False)),
        "workout": bool(opts.get("workout", False)),
        "sync_history_days": sync_history_days,
        "sync_sleep_spo2": sync_sleep_spo2,
        "duration": duration,
        "scan_timeout": float(opts.get("scan_timeout") or DEFAULT_SCAN_TIMEOUT),
        "connect_timeout": float(opts.get("connect_timeout") or DEFAULT_CONNECT_TIMEOUT),
        "direct_connect": bool(opts.get("direct_connect", True)),
        "band_tz": str(opts.get("band_tz") or os.getenv(ENV_BAND_TZ) or "").strip() or None,
        "device_name": str(opts.get("device_name") or os.getenv(ENV_DEVICE_NAME) or "").strip() or None,
    }
    return device_id, auth_key, normalized
