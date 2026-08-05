import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import yaml


def _build_parser():
    parser = argparse.ArgumentParser(description="Run OpenSportsLib inference for classification, localization, or VQA.")
    parser.add_argument(
        "--task",
        choices=("classification", "localization", "vqa"),
        required=True,
        help="Task to run.",
    )
    model_source = parser.add_mutually_exclusive_group(required=True)
    model_source.add_argument(
        "--config",
        default=None,
        help="Local OpenSportsLib config path.",
    )
    model_source.add_argument(
        "--hf-model",
        default=None,
        help=(
            "Hugging Face model repository ID. Downloads its OpenSportsLib "
            "config and checkpoint before inference."
        ),
    )
    parser.add_argument(
        "--hf-revision",
        default="main",
        help="Hugging Face branch, tag, or commit used with --hf-model (default: main).",
    )
    parser.add_argument(
        "--hf-token",
        default=None,
        help=(
            "Optional Hugging Face token for private/gated repositories. "
            "When omitted, the normal HF_TOKEN or local login is used."
        ),
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download the Hugging Face config and checkpoint even when cached.",
    )
    parser.add_argument(
        "--test-set",
        required=True,
        help="Dataset JSON.",
    )
    parser.add_argument(
        "--question",
        default=None,
        help="Question asked for every sample when --task vqa.",
    )
    parser.add_argument(
        "--weights",
        default=None,
        help="Optional checkpoint, adapter path, or model identifier.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Where to save predictions.",
    )
    return parser


def _download_hf_artifacts(repo_id, revision, token, force_download):
    annotation_tool_dir = Path(__file__).resolve().parents[1] / "annotation_tool"
    if str(annotation_tool_dir) not in sys.path:
        sys.path.insert(0, str(annotation_tool_dir))

    from hf_model_import import resolve_hf_local_model

    print(f"Hugging Face model: {repo_id}@{revision}")
    return resolve_hf_local_model(
        {
            "repo_id": repo_id,
            "revision": revision,
            "token": token,
            "force_download": force_download,
        },
        progress_cb=lambda message, current, total: print(
            f"[HF {current}/{total}] {message}"
        ),
    )


def _resolve_model_artifacts(args):
    if not args.hf_model:
        if args.hf_token or args.force_download:
            raise ValueError("--hf-token and --force-download require --hf-model.")
        return args.config, args.weights

    if args.config or args.weights:
        raise ValueError("--hf-model cannot be combined with --config or --weights.")
    revision = str(args.hf_revision or "main").strip() or "main"
    descriptor = _download_hf_artifacts(
        str(args.hf_model).strip(),
        revision,
        args.hf_token,
        args.force_download,
    )
    expected_task = "question_answer" if args.task == "vqa" else args.task
    downloaded_task = descriptor.get("task")
    if downloaded_task != expected_task:
        raise ValueError(
            f"Hugging Face model task is {downloaded_task!r}, but --task "
            f"{args.task!r} was requested."
        )
    print(f"cached config: {descriptor['config_path']}")
    print(f"cached weights: {descriptor['weights']}")
    return descriptor["config_path"], descriptor["weights"]


def _resolve_weights_path(weights):
    if not weights:
        return weights
    raw = str(weights)
    expanded = Path(raw).expanduser()
    looks_local = (
        expanded.is_absolute()
        or raw.startswith((".", "~"))
        or expanded.exists()
        or raw.endswith((".pt", ".pth", ".pth.tar", ".ckpt", ".bin", ".safetensors"))
    )
    if not looks_local:
        return raw
    resolved = str(expanded.resolve())
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"Weights file does not exist: {resolved}")
    return resolved


def _set_runtime_paths(config, workspace):
    system = config.setdefault("SYSTEM", {})
    paths = system.get("paths")
    if isinstance(paths, dict):
        paths["log_dir"] = str(workspace / "logs")
        paths["save_dir"] = str(workspace / "checkpoints")
        paths["work_dir"] = str(workspace)
    else:
        system["log_dir"] = str(workspace / "logs")
        system["save_dir"] = str(workspace / "checkpoints")
        system["work_dir"] = str(workspace)


def _set_test_data(config, test_set, data_root):
    data = config.setdefault("DATA", {})

    # Legacy OpenSportsLib configs are migrated when loaded, but overriding both
    # shapes also supports already-canonical configs.
    data["data_dir"] = data_root
    legacy_test = data.setdefault("test", {})
    legacy_test["path"] = test_set
    legacy_test["video_path"] = data_root
    legacy_loader = legacy_test.setdefault("dataloader", {})
    legacy_loader["num_workers"] = 0
    legacy_loader["shuffle"] = False
    legacy_loader["pin_memory"] = False

    common = data.get("common")
    if isinstance(common, dict):
        splits = common.setdefault("splits", {})
        canonical_test = splits.setdefault("test", {})
        canonical_test["annotation_path"] = test_set
        canonical_test["source_path"] = data_root
        canonical_loader = canonical_test.setdefault("dataloader", {})
        canonical_loader["num_workers"] = 0
        canonical_loader["shuffle"] = False
        canonical_loader["pin_memory"] = False


def _write_runtime_config(config_path, runtime_path, *, test_set):
    with open(config_path, encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    if not isinstance(config, dict):
        raise TypeError("--config must contain a YAML mapping.")

    workspace = runtime_path.parent
    _set_runtime_paths(config, workspace)
    if test_set:
        data_root = str(Path(test_set).parent)
        _set_test_data(config, test_set, data_root)

    with open(runtime_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)


def _write_vqa_question_dataset(test_set, output_path, question):
    with open(test_set, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise TypeError("--test-set must contain an object with a data list.")

    data_root = Path(test_set).parent
    for index, sample in enumerate(payload["data"]):
        if not isinstance(sample, dict):
            raise TypeError(f"Sample {index} in --test-set must be an object.")
        video_input = next(
            (
                item
                for item in sample.get("inputs", [])
                if isinstance(item, dict)
                and str(item.get("type") or "").lower() == "video"
                and str(item.get("path") or "").strip()
            ),
            None,
        )
        sample_id = sample.get("id", index)
        if video_input is None:
            raise ValueError(f"VQA sample {sample_id!r} has no video input.")
        video_path = Path(str(video_input["path"])).expanduser()
        resolved_video = video_path if video_path.is_absolute() else data_root / video_path
        if not resolved_video.is_file():
            raise FileNotFoundError(
                f"Video for VQA sample {sample_id!r} does not exist: {resolved_video}"
            )
        sample["answers"] = [{"question": question, "answers": []}]

    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return len(payload["data"])


def _build_model(task, config_path):
    from opensportslib.apis import ClassificationModel, LocalizationModel, VQAModel

    model_cls = {
        "classification": ClassificationModel,
        "localization": LocalizationModel,
        "vqa": VQAModel,
    }[task]
    return model_cls(config=config_path)


def _print_preview(task, predictions):
    rows = predictions.get("data", []) if isinstance(predictions, dict) else []
    print(f"task: {task}")
    print(f"num_predictions: {len(rows)}")
    if not rows:
        return

    first_row = rows[0]
    if task == "vqa":
        print(f"question: {first_row.get('question')}")
        print(f"answer: {first_row.get('answer_text')}")
        return

    print("first_prediction:")
    print(json.dumps(first_row, indent=2))


def main():
    parser = _build_parser()
    args = parser.parse_args()

    question = str(args.question or "").strip()
    if args.task == "vqa" and not question:
        parser.error("--question is required for --task vqa.")
    if args.task != "vqa" and question:
        parser.error("--question is supported only for --task vqa.")

    try:
        model_config, model_weights = _resolve_model_artifacts(args)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))

    config_path = str(Path(model_config).expanduser().resolve())
    output_path = str(Path(args.output).expanduser().resolve())
    weights = model_weights
    if not os.path.isfile(config_path):
        parser.error(f"Config file does not exist: {config_path}")
    try:
        weights = _resolve_weights_path(weights)
    except FileNotFoundError as exc:
        parser.error(str(exc))

    test_set = str(Path(args.test_set).expanduser().resolve())
    if not os.path.isfile(test_set):
        parser.error(f"Test set does not exist: {test_set}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="osl_inference_") as temp_dir:
        runtime_config = Path(temp_dir) / "runtime_config.yaml"
        _write_runtime_config(
            config_path,
            runtime_config,
            test_set=test_set,
        )
        print(f"runtime data root: {Path(test_set).parent}")

        inference_set = test_set
        if args.task == "vqa":
            inference_set = str(Path(temp_dir) / "vqa_test_set.json")
            try:
                sample_count = _write_vqa_question_dataset(
                    test_set,
                    inference_set,
                    question,
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                parser.error(str(exc))
            print(f"VQA question: {question}")
            print(f"VQA samples: {sample_count}")

        api = _build_model(args.task, str(runtime_config))
        predictions = api.infer(
            test_set=inference_set,
            weights=weights,
            use_wandb=False,
        )

        saved_path = api.save_predictions(
            output_path=output_path,
            predictions=predictions,
        )
    print(f"saved {saved_path}")
    _print_preview(args.task, predictions)


if __name__ == "__main__":
    main()
