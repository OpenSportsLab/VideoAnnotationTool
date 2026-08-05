"""Opt-in network/model-loading checks for curated OpenSportsLab repositories."""

import os

import pytest

from hf_model_import import resolve_hf_local_model


pytestmark = [
    pytest.mark.network,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("RUN_HF_MODEL_SMOKE") != "1",
        reason="Set RUN_HF_MODEL_SMOKE=1 to download and load curated checkpoints.",
    ),
]


@pytest.mark.parametrize(
    "repo_id",
    [
        "OpenSportsLab/OSL-cls-action-mvitv2",
        "OpenSportsLab/OSL-loc-snbas-2025-e2e",
        "OpenSportsLab/OSL-loc-snbas-2023-e2e",
    ],
)
def test_curated_model_can_be_constructed_and_load_cached_checkpoint(repo_id):
    from opensportslib import model

    descriptor = resolve_hf_local_model({"repo_id": repo_id, "revision": "main"})
    if descriptor["task"] == "classification":
        runner = model.ClassificationModel(config=descriptor["config_path"])
    else:
        runner = model.LocalizationModel(config=descriptor["config_path"])
    runner.load_weights(
        descriptor["weights"],
        trusted_legacy=descriptor.get("trusted_legacy", False),
    )
    assert runner.model is not None
