import importlib.metadata
import re
import subprocess


def setup_opensportslib():
    subprocess.check_call([
        "opensportslib",
        "setup",
    ])


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def _cuda_version_from_torch_package(torch_version: str) -> str:
    match = re.search(r"\+cu(\d+)", torch_version)
    if not match:
        return ""
    digits = match.group(1)
    return f"{digits[:-1]}.{digits[-1]}" if len(digits) >= 3 else digits


def opensportslib_environment_status() -> dict:
    """Report installed package and GPU runtime state without changing it."""
    opensportslib_version = _package_version("opensportslib")
    torch_version = _package_version("torch")
    cuda_version = _cuda_version_from_torch_package(torch_version)
    cuda_available = False
    gpu_name = ""
    try:
        import torch

        runtime_cuda = str(getattr(torch.version, "cuda", "") or "")
        cuda_version = cuda_version or runtime_cuda
        cuda_available = bool(torch.cuda.is_available())
        if cuda_available:
            gpu_name = str(torch.cuda.get_device_name(0))
    except Exception:
        # A broken or partially installed CUDA runtime should still leave the
        # versions dialog usable so setup can repair it.
        pass
    return {
        "opensportslib_version": opensportslib_version,
        "torch_version": torch_version,
        "gpu_support_installed": bool(cuda_version),
        "cuda_version": cuda_version,
        "cuda_available": cuda_available,
        "gpu_name": gpu_name,
    }
