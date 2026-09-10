"""Scoped control for Hugging Face's optional Xet transfer backend."""

from contextlib import contextmanager
import os
import sys
import threading


_HF_XET_LOCK = threading.RLock()


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return bool(default)
    return bool(value)


def setting_bool(value, default: bool = False) -> bool:
    return _as_bool(value, default)


@contextmanager
def temporary_hf_xet_disabled(disabled: bool):
    """Set the Xet mode for one transfer and restore the prior process state."""
    with _HF_XET_LOCK:
        previous_environment = os.environ.get("HF_HUB_DISABLE_XET")
        constants = sys.modules.get("huggingface_hub.constants")
        previous_constant = (
            getattr(constants, "HF_HUB_DISABLE_XET", None)
            if constants is not None
            else None
        )
        disabled = bool(disabled)
        os.environ["HF_HUB_DISABLE_XET"] = "1" if disabled else "0"
        if constants is not None:
            constants.HF_HUB_DISABLE_XET = disabled
        try:
            yield
        finally:
            if previous_environment is None:
                os.environ.pop("HF_HUB_DISABLE_XET", None)
            else:
                os.environ["HF_HUB_DISABLE_XET"] = previous_environment
            if constants is not None:
                constants.HF_HUB_DISABLE_XET = previous_constant
