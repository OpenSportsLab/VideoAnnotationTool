import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "tools" / "convert_legacy_vqa_to_grouped.py"

spec = importlib.util.spec_from_file_location("convert_legacy_vqa_to_grouped", SCRIPT_PATH)
convert_legacy_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(convert_legacy_module)

convert_legacy_vqa_to_grouped = convert_legacy_module.convert_legacy_vqa_to_grouped


def test_convert_legacy_vqa_merges_duplicate_samples_and_answers():
    payload = {
        "version": "2.0",
        "questions": [
            {"id": "q1", "question": "Is it a foul?"},
            {"id": "q2", "question": "What card?"},
        ],
        "data": [
            {
                "id": "action_0",
                "inputs": [{"type": "video", "path": "media/action_0/clip_0.mp4"}],
                "metadata": {"source_path": "Test/action_0"},
                "answers": [
                    {"question_id": "q1", "answer": "Yes."},
                    {"question_id": "q2", "answer": "Yellow."},
                ],
            },
            {
                "id": "action_0__2",
                "inputs": [{"type": "video", "path": "media/action_0/clip_0.mp4"}],
                "metadata": {"source_path": "Test/action_0", "changed": True},
                "answers": [
                    {"question_id": "q1", "answer": "Yes."},
                    {"question_id": "qmissing", "answer": "Drop."},
                ],
            },
        ],
    }

    converted, warnings = convert_legacy_vqa_to_grouped(payload)

    assert "questions" not in converted
    assert len(converted["data"]) == 1
    assert converted["data"][0]["id"] == "action_0"
    assert converted["data"][0]["metadata"] == {"source_path": "Test/action_0"}
    assert converted["data"][0]["answers"] == [
        {"question": "Is it a foul?", "answers": ["Yes.", "Yes."]},
        {"question": "What card?", "answers": ["Yellow."]},
    ]
    assert any("Keeping first non-QA fields" in warning for warning in warnings)
    assert any("unknown question_id" in warning for warning in warnings)
