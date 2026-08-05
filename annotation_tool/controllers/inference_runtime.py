"""Shared runtime capability resolution for direct OpenSportsLib inference."""

from __future__ import annotations


def cuda_is_available() -> bool:
    """Return whether the current OpenSportsLib process can use CUDA."""
    try:
        import torch

        return bool(torch.cuda.is_available())
    except (ImportError, RuntimeError):
        return False


def configure_compute_device(
    config_dict: dict, *, cuda_available: bool | None = None
) -> bool:
    """Resolve an OpenSportsLib config to CUDA or CPU for this process.

    Explicit CPU is preserved. ``auto`` and ``cuda`` use CUDA when it is
    available and otherwise become CPU. Both legacy and canonical GPU fields
    are normalized for the CPU fallback. Returns whether CUDA was selected.
    """
    system_cfg = config_dict.setdefault("SYSTEM", {})
    requested_device = str(system_cfg.get("device") or "auto").strip().lower()
    has_cuda = cuda_is_available() if cuda_available is None else bool(cuda_available)
    use_cuda = requested_device != "cpu" and has_cuda
    system_cfg["device"] = requested_device if use_cuda else "cpu"

    if not use_cuda:
        system_cfg["GPU"] = -1
        system_cfg["gpu_id"] = -1
        gpu_cfg = system_cfg.get("gpu")
        if isinstance(gpu_cfg, dict):
            gpu_cfg["count"] = 0
            gpu_cfg["id"] = 0
    return use_cuda
