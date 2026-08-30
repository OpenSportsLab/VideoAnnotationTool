"""Inspect and cache OpenSportsLib model repositories from Hugging Face."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

from huggingface_hub import HfApi, hf_hub_download
from inference_settings import TRUSTED_LEGACY_HF_MODEL_IDS
from inference_types import INFERENCE_TASKS
from opensportslib.core.config import load_config_omega
from opensportslib.core.config.accessors import get_model_family

CONFIG_FILENAMES = ("config.yaml", "config.yml", "config.json")
CHECKPOINT_SUFFIXES = (".safetensors", ".pth.tar", ".pth", ".pt", ".bin")
RULE_BASED_MODEL_FAMILY = "rulebased"
PREFERRED_CHECKPOINT_FILENAMES = (
    "model.safetensors",
    "model.pth.tar",
    "model.pth",
    "model.pt",
    "checkpoint.pth.tar",
    "checkpoint.pth",
    "checkpoint.pt",
    "pytorch_model.bin",
    "model.bin",
)


class HfModelImportCancelled(RuntimeError):
    pass


def _check_cancelled(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled and is_cancelled():
        raise HfModelImportCancelled("Model download cancelled.")


def _emit_progress(progress_cb, message: str, current: int, total: int) -> None:
    if progress_cb:
        progress_cb(message, current, total)


def _repository_filenames(model_info) -> list[str]:
    names = []
    for sibling in list(getattr(model_info, "siblings", None) or []):
        name = str(getattr(sibling, "rfilename", "") or "").strip()
        if name:
            names.append(name)
    return names


def select_config_filename(filenames: list[str]) -> str:
    available = set(filenames)
    for candidate in CONFIG_FILENAMES:
        if candidate in available:
            return candidate
    nested = sorted(
        name
        for name in filenames
        if PurePosixPath(name).name.lower() in CONFIG_FILENAMES
    )
    if len(nested) == 1:
        return nested[0]
    if len(nested) > 1:
        raise ValueError(
            "Repository contains multiple OpenSportsLib configuration files: "
            f"{', '.join(nested)}"
        )
    raise ValueError(
        "Repository does not contain config.yaml, config.yml, or config.json."
    )


def _is_checkpoint(filename: str) -> bool:
    lowered = filename.lower()
    return any(lowered.endswith(suffix) for suffix in CHECKPOINT_SUFFIXES)


def select_checkpoint_filename(filenames: list[str]) -> str:
    candidates = sorted(name for name in filenames if _is_checkpoint(name))
    if not candidates:
        raise ValueError("Repository does not contain a supported model checkpoint.")

    by_basename: dict[str, list[str]] = {}
    for candidate in candidates:
        by_basename.setdefault(PurePosixPath(candidate).name.lower(), []).append(candidate)
    for preferred in PREFERRED_CHECKPOINT_FILENAMES:
        matches = by_basename.get(preferred, [])
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(
                f"Repository contains multiple checkpoints named {preferred!r}; "
                "remove the ambiguity before importing it."
            )
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(
        "Repository contains multiple checkpoint files and none has a preferred "
        f"standard name: {', '.join(candidates)}"
    )


def parse_opensportslib_task(config_path: str) -> tuple[str, bool]:
    """Load a downloaded config via OpenSportsLib's own loader and report its task.

    Reusing ``load_config_omega``/``get_model_family`` (instead of hand-parsing
    the YAML/JSON) means the same schema validation and model-family detection
    OpenSportsLib itself relies on also gates what the Video Annotation Tool
    accepts, and it lets us recognize checkpoint-free rule-based models, which
    have no MODEL/DATA structure resembling a trainable model config.
    """
    try:
        config = load_config_omega(config_path)
    except Exception as exc:
        raise ValueError(f"Could not parse OpenSportsLib configuration: {exc}") from exc
    task = str(getattr(config, "TASK", "") or "").strip().lower()
    if task == "vqa":
        task = "question_answer"
    if task not in INFERENCE_TASKS:
        supported = ", ".join(sorted(INFERENCE_TASKS))
        raise ValueError(
            f"Configuration has unsupported or missing OpenSportsLib task {task!r}; "
            f"expected one of: {supported}."
        )
    is_rule_based = get_model_family(config).strip().lower() == RULE_BASED_MODEL_FAMILY
    return task, is_rule_based


def resolve_hf_local_model(
    config: dict[str, Any],
    *,
    progress_cb: Callable[[str, int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Inspect a repository, cache its config/checkpoint, and return a registry row."""
    repo_id = str(config.get("repo_id") or "").strip()
    revision = str(config.get("revision") or "main").strip() or "main"
    token = str(config.get("token") or "").strip() or None
    force_download = bool(config.get("force_download", False))
    if not repo_id or "/" not in repo_id or repo_id.startswith("/") or repo_id.endswith("/"):
        raise ValueError("Enter a Hugging Face repository ID such as owner/model-name.")

    _check_cancelled(is_cancelled)
    _emit_progress(progress_cb, "Inspecting repository…", 0, 3)
    info = HfApi().model_info(
        repo_id=repo_id,
        revision=revision,
        token=token,
        files_metadata=True,
    )
    _check_cancelled(is_cancelled)
    filenames = _repository_filenames(info)
    config_filename = select_config_filename(filenames)

    _emit_progress(progress_cb, f"Downloading {config_filename}…", 1, 3)
    config_path = hf_hub_download(
        repo_id=repo_id,
        filename=config_filename,
        revision=revision,
        token=token,
        force_download=force_download,
    )
    _check_cancelled(is_cancelled)
    task, is_rule_based = parse_opensportslib_task(config_path)

    # Rule-based models (e.g. OpenSportsLab/skeleton-header-max-recall) run
    # from their config alone and have no checkpoint to fetch.
    weights_path = None
    checkpoint_filename = ""
    if is_rule_based:
        _emit_progress(progress_cb, "Rule-based model has no checkpoint to download.", 2, 3)
    else:
        checkpoint_filename = select_checkpoint_filename(filenames)
        _emit_progress(progress_cb, f"Downloading {checkpoint_filename}…", 2, 3)
        weights_path = hf_hub_download(
            repo_id=repo_id,
            filename=checkpoint_filename,
            revision=revision,
            token=token,
            force_download=force_download,
        )
        _check_cancelled(is_cancelled)

    descriptor = {
        "task": task,
        "id": repo_id,
        "display_name": repo_id.rsplit("/", 1)[-1],
        "config_path": os.path.abspath(config_path),
        "weights": os.path.abspath(weights_path) if weights_path else "",
        "available": True,
        "accepted_input_types": ["video"],
        "supports_time_range": task in {"localization", "dense_description"},
        "hf_repo_id": repo_id,
        "hf_revision": revision,
        "hf_checkpoint_filename": checkpoint_filename,
        "checkpoint_free": is_rule_based,
        "trusted_legacy": (not is_rule_based)
        and task == "localization"
        and repo_id in TRUSTED_LEGACY_HF_MODEL_IDS
        and revision == "main",
    }
    _emit_progress(progress_cb, "Model cached and ready to add.", 3, 3)
    return descriptor
