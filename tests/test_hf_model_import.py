from types import SimpleNamespace

import hf_model_import
import pytest
import yaml
from hf_model_import import (
    HfModelImportCancelled,
    parse_opensportslib_task,
    resolve_hf_local_model,
    select_checkpoint_filename,
    select_config_filename,
)


def _model_info(*filenames):
    return SimpleNamespace(
        siblings=[SimpleNamespace(rfilename=filename) for filename in filenames]
    )


def _canonical_config(task="classification", family="custom", **overrides):
    """Minimal config that satisfies OpenSportsLib's canonical-schema validator."""
    components = {
        "encoder": {"kind": "encoder", "source": {"provider": "opensportslib"}}
    }
    data = {"common": {"classes": ["a", "b"]}}
    if str(task).strip().lower() == "vqa":
        components["decoder"] = {"kind": "decoder", "source": {"provider": "opensportslib"}}
        data["inputs"] = {"video": {}, "question": {}}
    config = {
        "TASK": task,
        "VERSION": 2,
        "SYSTEM": {"device": "cpu"},
        "DATA": data,
        "MODEL": {
            "metadata": {"family": family},
            "components": components,
            "topology": [],
        },
        "TRAIN": {"trainer": {"type": "trainer_default"}},
    }
    config.update(overrides)
    return config


def _write_config(path, task="classification", family="custom", dumper=yaml.safe_dump, **overrides):
    config = _canonical_config(task=task, family=family, **overrides)
    with open(path, "w", encoding="utf-8") as handle:
        dumper(config, handle)
    return path


def test_checkpoint_selection_prefers_standard_name_and_rejects_ambiguity():
    assert select_checkpoint_filename(["epoch_9.pt", "model.safetensors"]) == (
        "model.safetensors"
    )
    assert select_checkpoint_filename(["weights/custom.pth"]) == "weights/custom.pth"
    with pytest.raises(ValueError, match="multiple checkpoint"):
        select_checkpoint_filename(["one.pt", "two.bin"])
    with pytest.raises(ValueError, match="supported model checkpoint"):
        select_checkpoint_filename(["README.md"])


def test_config_selection_prefers_root_and_accepts_one_nested_config():
    assert select_config_filename(["configs/config.yaml"]) == "configs/config.yaml"
    assert select_config_filename(["other/config.yml", "config.json"]) == "config.json"
    with pytest.raises(ValueError, match="multiple OpenSportsLib configuration"):
        select_config_filename(["a/config.yaml", "b/config.json"])


@pytest.mark.parametrize(
    ("filename", "task", "family", "expected_task", "expected_rule_based"),
    [
        ("config.yaml", "classification", "custom", "classification", False),
        ("config.yml", "localization", "custom", "localization", False),
        ("config.yaml", "VQA", "custom", "question_answer", False),
        ("config.yaml", "localization", "RuleBased", "localization", True),
    ],
)
def test_parse_opensportslib_task(
    filename, task, family, expected_task, expected_rule_based, tmp_path
):
    path = tmp_path / filename
    dumper = (
        (lambda cfg, handle: __import__("json").dump(cfg, handle))
        if filename.endswith(".json")
        else yaml.safe_dump
    )
    _write_config(str(path), task=task, family=family, dumper=dumper)
    assert parse_opensportslib_task(str(path)) == (expected_task, expected_rule_based)


def test_parse_opensportslib_task_rejects_malformed_or_unsupported(tmp_path):
    malformed = tmp_path / "config.yaml"
    malformed.write_text("[broken", encoding="utf-8")
    with pytest.raises(ValueError, match="Could not parse"):
        parse_opensportslib_task(str(malformed))

    unsupported = tmp_path / "config.yml"
    _write_config(str(unsupported), task="segmentation")
    with pytest.raises(ValueError, match="unsupported or missing"):
        parse_opensportslib_task(str(unsupported))


def test_resolve_downloads_config_and_checkpoint_with_revision_and_token(
    monkeypatch, tmp_path
):
    info = _model_info("config.yaml", "model.pth.tar", "extra.bin")
    calls = []
    config_path = tmp_path / "config.yaml"
    _write_config(str(config_path), task="classification")
    weights_path = tmp_path / "model.pth.tar"
    weights_path.write_bytes(b"checkpoint")

    class FakeApi:
        def model_info(self, **kwargs):
            calls.append(("info", kwargs))
            return info

    def fake_download(**kwargs):
        calls.append(("download", kwargs))
        return str(config_path if kwargs["filename"] == "config.yaml" else weights_path)

    monkeypatch.setattr(hf_model_import, "HfApi", FakeApi)
    monkeypatch.setattr(hf_model_import, "hf_hub_download", fake_download)
    progress = []
    model = resolve_hf_local_model(
        {
            "repo_id": "owner/model",
            "revision": "v1",
            "token": "hf_test",
            "force_download": True,
        },
        progress_cb=lambda *args: progress.append(args),
    )

    assert model["task"] == "classification"
    assert model["id"] == "owner/model"
    assert model["config_path"] == str(config_path)
    assert model["weights"] == str(weights_path)
    assert model["hf_revision"] == "v1"
    assert model["hf_checkpoint_filename"] == "model.pth.tar"
    assert model["trusted_legacy"] is False
    assert model["checkpoint_free"] is False
    assert calls[0][1]["files_metadata"] is True
    assert all(call[1]["token"] == "hf_test" for call in calls)
    download_calls = [call for kind, call in calls if kind == "download"]
    assert len(download_calls) == 2
    assert all(call["force_download"] is True for call in download_calls)
    assert progress[-1] == ("Model cached and ready to add.", 3, 3)


def test_resolve_grants_legacy_only_to_allowlisted_official_repo(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    _write_config(str(config_path), task="localization")
    weights_path = tmp_path / "model.pt"
    weights_path.write_bytes(b"legacy")

    class FakeApi:
        def model_info(self, **_kwargs):
            return _model_info("config.yaml", "model.pt")

    monkeypatch.setattr(hf_model_import, "HfApi", FakeApi)
    monkeypatch.setattr(
        hf_model_import,
        "hf_hub_download",
        lambda **kwargs: str(
            config_path if kwargs["filename"] == "config.yaml" else weights_path
        ),
    )
    trusted = resolve_hf_local_model(
        {"repo_id": "OpenSportsLab/OSL-loc-snbas-2025-e2e"}
    )
    other_revision = resolve_hf_local_model(
        {
            "repo_id": "OpenSportsLab/OSL-loc-snbas-2025-e2e",
            "revision": "experimental",
        }
    )
    arbitrary = resolve_hf_local_model({"repo_id": "owner/legacy-model"})
    assert trusted["trusted_legacy"] is True
    assert other_revision["trusted_legacy"] is False
    assert arbitrary["trusted_legacy"] is False


def test_resolve_rule_based_model_skips_checkpoint_download(monkeypatch, tmp_path):
    """A rule-based repo (config.yaml only, no checkpoint) must import cleanly."""
    config_path = tmp_path / "config.yaml"
    _write_config(str(config_path), task="localization", family="RuleBased")

    class FakeApi:
        def model_info(self, **_kwargs):
            return _model_info("config.yaml")

    download_calls = []

    def fake_download(**kwargs):
        download_calls.append(kwargs["filename"])
        return str(config_path)

    monkeypatch.setattr(hf_model_import, "HfApi", FakeApi)
    monkeypatch.setattr(hf_model_import, "hf_hub_download", fake_download)

    model = resolve_hf_local_model(
        {"repo_id": "OpenSportsLab/skeleton-header-max-recall"}
    )

    assert model["checkpoint_free"] is True
    assert model["weights"] == ""
    assert model["hf_checkpoint_filename"] == ""
    assert model["trusted_legacy"] is False
    assert download_calls == ["config.yaml"]


def test_resolve_checks_cancellation_after_blocking_repository_inspection(monkeypatch):
    cancelled = False

    class FakeApi:
        def model_info(self, **_kwargs):
            nonlocal cancelled
            cancelled = True
            return _model_info("config.yaml", "model.pt")

    monkeypatch.setattr(hf_model_import, "HfApi", FakeApi)
    with pytest.raises(HfModelImportCancelled):
        resolve_hf_local_model(
            {"repo_id": "owner/model"}, is_cancelled=lambda: cancelled
        )


def test_private_repository_errors_are_propagated(monkeypatch):
    class FakeApi:
        def model_info(self, **_kwargs):
            raise RuntimeError("401 private repository")

    monkeypatch.setattr(hf_model_import, "HfApi", FakeApi)
    with pytest.raises(RuntimeError, match="private repository"):
        resolve_hf_local_model({"repo_id": "owner/private"})
