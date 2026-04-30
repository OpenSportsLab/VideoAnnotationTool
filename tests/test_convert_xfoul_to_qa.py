import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "test_data" / "convert_xfoul_to_qa.py"

spec = importlib.util.spec_from_file_location("convert_xfoul_to_qa", SCRIPT_PATH)
convert_xfoul_to_qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(convert_xfoul_to_qa)

convert_xfoul_rows_to_osl_qa = convert_xfoul_to_qa.convert_xfoul_rows_to_osl_qa


def test_convert_xfoul_rows_emits_grouped_vqa_answers():
    rows = [
        {
            "path": "Test/action_0",
            "video1": "https://example.test/clip_0.mp4",
            "video2": "https://example.test/clip_1.mp4",
            "question": "Is it a foul?",
            "answer": "Yes.",
        },
        {
            "path": "Test/action_0",
            "video1": "https://example.test/clip_0.mp4",
            "video2": "https://example.test/clip_1.mp4",
            "question": "What card?",
            "answer": "Yellow.",
        },
        {
            "path": "Test/action_0",
            "video1": "https://example.test/clip_0.mp4",
            "video2": "https://example.test/clip_1.mp4",
            "question": "Is it a foul?",
            "answer": "Yes, reckless.",
        },
    ]

    payload, downloads = convert_xfoul_rows_to_osl_qa(
        rows,
        input_json_path=Path("annotations_test.json"),
        media_dir="media",
    )

    assert "questions" not in payload
    assert len(payload["data"]) == 1
    assert payload["data"][0]["id"] == "action_0"
    assert payload["data"][0]["answers"] == [
        {"question": "Is it a foul?", "answers": ["Yes.", "Yes, reckless."]},
        {"question": "What card?", "answers": ["Yellow."]},
    ]
    assert downloads == [
        ("https://example.test/clip_0.mp4", "media/action_0/clip_0.mp4"),
        ("https://example.test/clip_1.mp4", "media/action_0/clip_1.mp4"),
    ]
