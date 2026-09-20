"""Persistent application-wide inference preferences."""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from typing import Any
from urllib.parse import urlparse, urlunparse

from inference_types import INFERENCE_TASKS


SERVER_URL_KEY = "inference/server_url"
REMOTE_ENABLED_KEY = "inference/remote_enabled"
REMOTE_ADMIN_TOKEN_KEY = "inference/remote_admin_token"
LOCAL_MODELS_KEY = "inference/local_models"
LOCAL_MODELS_SCHEMA_VERSION_KEY = "inference/local_models_schema_version"
LOCAL_MODELS_SCHEMA_VERSION = 2

DEFAULT_SERVER_URL = "http://127.0.0.1:8000"
LAST_MODEL_KEY_PREFIX = "inference/last_model"
LOCALIZATION_MIN_CONFIDENCE_PERCENT_KEY = "inference/localization_min_confidence_percent"
INFERENCE_PROVIDERS_KEY = "inference/providers"
INFERENCE_PROVIDERS_SCHEMA_VERSION_KEY = "inference/providers_schema_version"
INFERENCE_PROVIDERS_SCHEMA_VERSION = 2
INFERENCE_PROVIDER_TOKENS_KEY = "inference/provider_tokens"
LOCAL_PROVIDER_ID = "local"

KNOWN_HF_LOCAL_MODEL_IDS = (
    "OpenSportsLab/OSL-cls-action-mvitv2",
    "OpenSportsLab/OSL-loc-snbas-2025-e2e",
    "OpenSportsLab/OSL-loc-snbas-2023-e2e",
)

# Filter defaults persisted by releases that shipped these retired models.
RETIRED_LOCAL_MODEL_IDS = frozenset(
    {
        "jeetv/snpro-classification-mvit",
        "jeetv/snpro-snbas-2024",
    }
)

TRUSTED_LEGACY_HF_MODEL_IDS = frozenset(
    {
        "OpenSportsLab/OSL-loc-snbas-2025-e2e",
        "OpenSportsLab/OSL-loc-snbas-2023-e2e",
    }
)


def _setting_bool(value, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def remote_inference_enabled(settings) -> bool:
    raw_providers = _json_setting(settings, INFERENCE_PROVIDERS_KEY, None)
    if isinstance(raw_providers, list):
        return any(
            isinstance(provider, dict)
            and provider.get("kind") == "remote"
            and _setting_bool(provider.get("enabled"))
            for provider in raw_providers
        )
    value = settings.value(REMOTE_ENABLED_KEY, False) if settings is not None else False
    return _setting_bool(value)


def last_model_key(task: str) -> str:
    if task not in INFERENCE_TASKS:
        raise ValueError(f"Unsupported inference task: {task!r}")
    return f"{LAST_MODEL_KEY_PREFIX}/{task}"


def load_last_model_choice(settings, task: str) -> tuple[str, str] | None:
    payload = _json_setting(settings, last_model_key(task), {})
    if not isinstance(payload, dict):
        return None
    provider_id = str(payload.get("provider_id") or payload.get("backend") or "")
    model_id = str(payload.get("model_id") or "").strip()
    if not provider_id or not model_id:
        return None
    if provider_id == "remote":
        remote = next(
            (
                provider
                for provider in load_inference_providers(settings)
                if provider["kind"] == "remote"
            ),
            None,
        )
        if remote is not None:
            provider_id = remote["id"]
    return provider_id, model_id


def save_last_model_choice(settings, task: str, provider_id: str, model_id: str) -> None:
    provider_id = str(provider_id or "").strip()
    model_id = str(model_id or "").strip()
    if settings is None or not provider_id or not model_id:
        return
    settings.setValue(
        last_model_key(task),
        json.dumps({"provider_id": provider_id, "model_id": model_id}),
    )
    settings.sync()


def normalize_localization_min_confidence_percent(value) -> float:
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(percent):
        return 0.0
    return round(max(0.0, min(100.0, percent)), 1)


def load_localization_min_confidence_percent(settings) -> float:
    if settings is None:
        return 0.0
    return normalize_localization_min_confidence_percent(
        settings.value(LOCALIZATION_MIN_CONFIDENCE_PERCENT_KEY, 0.0)
    )


def save_localization_min_confidence_percent(settings, value) -> None:
    if settings is None:
        return
    settings.setValue(
        LOCALIZATION_MIN_CONFIDENCE_PERCENT_KEY,
        normalize_localization_min_confidence_percent(value),
    )
    settings.sync()


def trusted_legacy_allowed(model: dict[str, Any]) -> bool:
    """Return whether a registry entry may opt into pickle deserialization."""
    if str(model.get("task") or "") != "localization":
        return False
    model_id = str(model.get("id") or "").strip()
    repo_id = str(model.get("hf_repo_id") or "").strip()
    revision = str(model.get("hf_revision") or "main").strip() or "main"
    weights = str(model.get("weights") or "").strip()
    if not repo_id and weights == model_id:
        repo_id = model_id
    return bool(
        model.get("trusted_legacy", False)
        and model_id == repo_id
        and repo_id in TRUSTED_LEGACY_HF_MODEL_IDS
        and revision == "main"
    )


def _is_obsolete_seeded_model(model: dict[str, Any]) -> bool:
    """Identify model rows automatically inserted by earlier releases."""
    model_id = str(model.get("id") or "").strip()
    weights = str(model.get("weights") or "").strip()
    repo_id = str(model.get("hf_repo_id") or model_id).strip()
    return bool(
        model_id in KNOWN_HF_LOCAL_MODEL_IDS
        and repo_id == model_id
        and weights == model_id
    )


def _json_setting(settings, key: str, default):
    raw = settings.value(key, "") if settings is not None else ""
    if isinstance(raw, (list, dict)):
        return raw
    try:
        value = json.loads(str(raw or ""))
    except Exception:
        return default
    return value


def _normalize_local_models(configured, schema_version) -> list[dict[str, Any]]:
    migrate_old_seeds = schema_version < LOCAL_MODELS_SCHEMA_VERSION
    models = configured if isinstance(configured, list) else []
    out_by_key = {}
    for model in models:
        if not isinstance(model, dict):
            continue
        task = str(model.get("task") or "")
        model_id = str(model.get("id") or "").strip()
        if model_id in RETIRED_LOCAL_MODEL_IDS or (
            migrate_old_seeds and _is_obsolete_seeded_model(model)
        ):
            continue
        if task in INFERENCE_TASKS and model_id:
            key = (task, model_id)
            merged = {**out_by_key.get(key, {}), **dict(model)}
            merged["trusted_legacy"] = trusted_legacy_allowed(merged)
            out_by_key[key] = merged
    return list(out_by_key.values())


def load_local_models(settings) -> list[dict[str, Any]]:
    provider_payload = _json_setting(settings, INFERENCE_PROVIDERS_KEY, None)
    if isinstance(provider_payload, list):
        local = next(
            (
                provider for provider in provider_payload
                if isinstance(provider, dict) and provider.get("kind") == "local"
            ),
            {},
        )
        return _normalize_local_models(
            local.get("models", []), LOCAL_MODELS_SCHEMA_VERSION
        )
    configured = _json_setting(settings, LOCAL_MODELS_KEY, [])
    try:
        schema_version = int(
            settings.value(LOCAL_MODELS_SCHEMA_VERSION_KEY, 0)
            if settings is not None
            else 0
        )
    except (TypeError, ValueError):
        schema_version = 0
    return _normalize_local_models(configured, schema_version)


def save_local_models(settings, models) -> None:
    if isinstance(_json_setting(settings, INFERENCE_PROVIDERS_KEY, None), list):
        providers = load_inference_providers(settings)
        for provider in providers:
            if provider["id"] == LOCAL_PROVIDER_ID:
                provider["models"] = list(models or [])
                break
        save_inference_providers(settings, providers)
        return
    settings.setValue(LOCAL_MODELS_KEY, json.dumps(list(models or [])))
    settings.setValue(LOCAL_MODELS_SCHEMA_VERSION_KEY, LOCAL_MODELS_SCHEMA_VERSION)


def normalize_server_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("Server URL must start with http:// or https://.")
    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValueError("Server URL must include a host.")
    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), netloc, path, "", "", ""))


def _provider_name_for_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or "Remote Server"


def _normalized_catalog(raw_catalog) -> list[dict[str, Any]]:
    catalog = []
    seen = set()
    for item in list(raw_catalog or []):
        if not isinstance(item, dict):
            continue
        task = str(item.get("task") or "")
        model_id = str(item.get("id") or "").strip()
        if task not in INFERENCE_TASKS or not model_id or (task, model_id) in seen:
            continue
        seen.add((task, model_id))
        catalog.append(dict(item))
    return catalog


def _normalize_provider(provider: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(provider.get("kind") or "").strip().lower()
    if kind not in {"local", "remote"}:
        return None
    provider_id = str(provider.get("id") or "").strip()
    if kind == "local":
        provider_id = LOCAL_PROVIDER_ID
    if not provider_id:
        return None
    try:
        catalog_updated_at = float(provider.get("catalog_updated_at") or 0.0)
    except (TypeError, ValueError):
        catalog_updated_at = 0.0
    normalized = {
        "id": provider_id,
        "kind": kind,
        "name": str(provider.get("name") or ("Local" if kind == "local" else "Remote Server")).strip(),
        "enabled": True if kind == "local" else _setting_bool(provider.get("enabled", True)),
        "models": _normalized_catalog(provider.get("models")),
        "catalog_updated_at": catalog_updated_at,
        "connection_status": str(provider.get("connection_status") or ""),
    }
    if kind == "remote":
        try:
            normalized["url"] = normalize_server_url(provider.get("url"))
        except ValueError:
            return None
        normalized["admin_token"] = str(provider.get("admin_token") or "")
    return normalized


def _validate_provider_registry(providers) -> list[dict[str, Any]]:
    normalized = []
    ids = set()
    names = set()
    urls = set()
    local_seen = False
    for raw in list(providers or []):
        if not isinstance(raw, dict):
            continue
        provider = _normalize_provider(raw)
        if provider is None:
            continue
        provider_id = provider["id"]
        name_key = provider["name"].casefold()
        url_key = provider.get("url", "").casefold()
        if provider_id in ids or not provider["name"] or name_key in names:
            continue
        if provider["kind"] == "remote" and (not url_key or url_key in urls):
            continue
        if provider["kind"] == "local":
            if local_seen:
                continue
            local_seen = True
        ids.add(provider_id)
        names.add(name_key)
        if url_key:
            urls.add(url_key)
        normalized.append(provider)
    if not local_seen:
        normalized.insert(0, {
            "id": LOCAL_PROVIDER_ID,
            "kind": "local",
            "name": "Local",
            "enabled": True,
            "models": [],
            "catalog_updated_at": 0.0,
            "connection_status": "",
        })
    normalized.sort(key=lambda item: (item["kind"] != "local",))
    return normalized


def _legacy_providers(settings) -> list[dict[str, Any]]:
    providers = [{
        "id": LOCAL_PROVIDER_ID,
        "kind": "local",
        "name": "Local",
        "enabled": True,
        "models": load_local_models(settings),
        "catalog_updated_at": 0.0,
        "connection_status": "",
    }]
    raw_url = settings.value(SERVER_URL_KEY, None) if settings is not None else None
    raw_enabled = settings.value(REMOTE_ENABLED_KEY, None) if settings is not None else None
    raw_token = settings.value(REMOTE_ADMIN_TOKEN_KEY, None) if settings is not None else None
    if raw_url is not None or raw_enabled is not None or raw_token not in (None, ""):
        try:
            url = normalize_server_url(raw_url or DEFAULT_SERVER_URL)
        except ValueError:
            url = DEFAULT_SERVER_URL
        providers.append({
            "id": f"remote-{uuid.uuid5(uuid.NAMESPACE_URL, url).hex}",
            "kind": "remote",
            "name": _provider_name_for_url(url),
            "enabled": _setting_bool(raw_enabled),
            "url": url,
            "models": [],
            "catalog_updated_at": 0.0,
            "connection_status": "",
            "admin_token": str(raw_token or ""),
        })
    return providers


def load_inference_providers(settings, *, migrate: bool = True) -> list[dict[str, Any]]:
    raw = _json_setting(settings, INFERENCE_PROVIDERS_KEY, None)
    migrated = not isinstance(raw, list)
    providers = _validate_provider_registry(
        _legacy_providers(settings) if migrated else raw
    )
    tokens = _json_setting(settings, INFERENCE_PROVIDER_TOKENS_KEY, {})
    tokens = tokens if isinstance(tokens, dict) else {}
    for provider in providers:
        if provider["kind"] == "remote":
            provider["admin_token"] = str(
                tokens.get(provider["id"], provider.get("admin_token", "")) or ""
            )
    if migrated and migrate and settings is not None:
        save_inference_providers(settings, providers)
        first_remote = next(
            (provider for provider in providers if provider["kind"] == "remote"), None
        )
        for task in INFERENCE_TASKS:
            key = last_model_key(task)
            choice = _json_setting(settings, key, {})
            if not isinstance(choice, dict) or "provider_id" in choice:
                continue
            backend = str(choice.get("backend") or "")
            model_id = str(choice.get("model_id") or "")
            provider_id = (
                LOCAL_PROVIDER_ID if backend == "local"
                else first_remote["id"] if backend == "remote" and first_remote else ""
            )
            if provider_id and model_id:
                settings.setValue(
                    key, json.dumps({"provider_id": provider_id, "model_id": model_id})
                )
        remove = getattr(settings, "remove", None)
        if callable(remove):
            for key in (
                SERVER_URL_KEY,
                REMOTE_ENABLED_KEY,
                REMOTE_ADMIN_TOKEN_KEY,
                LOCAL_MODELS_KEY,
                LOCAL_MODELS_SCHEMA_VERSION_KEY,
            ):
                remove(key)
        settings.sync()
    return providers


def save_inference_providers(settings, providers) -> list[dict[str, Any]]:
    raw_providers = [item for item in list(providers or []) if isinstance(item, dict)]
    if not any(item.get("kind") == "local" for item in raw_providers):
        raw_providers.insert(0, {
            "id": LOCAL_PROVIDER_ID, "kind": "local", "name": "Local",
            "enabled": True, "models": [],
            "catalog_updated_at": 0.0, "connection_status": "",
        })
    names = [str(item.get("name") or "").strip().casefold() for item in raw_providers]
    urls = []
    for item in raw_providers:
        if item.get("kind") == "remote":
            urls.append(normalize_server_url(item.get("url")).casefold())
    if any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("Provider names must be non-empty and unique.")
    if len(urls) != len(set(urls)):
        raise ValueError("Remote server URLs must be unique.")
    if settings is None:
        return _validate_provider_registry(raw_providers)
    normalized = _validate_provider_registry(raw_providers)
    tokens = {
        provider["id"]: str(provider.get("admin_token") or "")
        for provider in raw_providers
        if isinstance(provider, dict)
        and provider.get("kind") == "remote"
        and provider.get("id")
    }
    persisted = []
    for provider in normalized:
        item = dict(provider)
        item.pop("admin_token", None)
        persisted.append(item)
    settings.setValue(INFERENCE_PROVIDERS_KEY, json.dumps(persisted))
    settings.setValue(
        INFERENCE_PROVIDERS_SCHEMA_VERSION_KEY,
        INFERENCE_PROVIDERS_SCHEMA_VERSION,
    )
    settings.setValue(INFERENCE_PROVIDER_TOKENS_KEY, json.dumps(tokens))
    settings.sync()
    return load_inference_providers(settings, migrate=False)


def new_remote_provider(name: str, url: str) -> dict[str, Any]:
    normalized_url = normalize_server_url(url)
    return {
        "id": f"remote-{uuid.uuid4().hex}",
        "kind": "remote",
        "name": str(name or _provider_name_for_url(normalized_url)).strip(),
        "enabled": True,
        "url": normalized_url,
        "admin_token": "",
        "models": [],
        "catalog_updated_at": 0.0,
        "connection_status": "",
    }


def update_provider_catalog(settings, provider_id: str, models, *, status="") -> bool:
    providers = load_inference_providers(settings)
    for provider in providers:
        if provider["id"] != provider_id:
            continue
        provider["models"] = [
            model.to_dict() if hasattr(model, "to_dict") else dict(model)
            for model in list(models or [])
        ]
        provider["catalog_updated_at"] = time.time()
        provider["connection_status"] = str(status or "Ready")
        save_inference_providers(settings, providers)
        return True
    return False


def update_provider_status(settings, provider_id: str, status: str) -> bool:
    providers = load_inference_providers(settings)
    for provider in providers:
        if provider["id"] == provider_id:
            provider["connection_status"] = str(status or "")
            save_inference_providers(settings, providers)
            return True
    return False
