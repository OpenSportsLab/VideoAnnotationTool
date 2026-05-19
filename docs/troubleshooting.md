# Troubleshooting

## App Fails to Start

- Confirm your environment is active.
- Reinstall dependencies:

```bash
pip install -r requirements.txt
```

## Dataset JSON Does Not Load

- Confirm the file is valid JSON.
- Confirm the root value is a JSON object, not an array.
- Confirm top-level `data` is a list.
- Check the expected structure in [OSL JSON Format](OSL.md).

Legacy VQA files that use top-level `questions` and per-answer `question_id`
entries should be converted before editing:

```bash
python tools/convert_legacy_vqa_to_grouped.py \
  --input-json old_vqa.json \
  --output-json grouped_vqa.json
```

## Media Files Are Missing After Loading

Relative paths in `data[].inputs[].path` are resolved from the directory that
contains the dataset JSON. If the JSON was moved separately from its media
folders, move the folders back beside the JSON or update the paths.

!!! tip "Saving can repair path layout"
    After opening a dataset from the intended folder, **Save Dataset As** can
    rewrite input paths relative to the new JSON location.

## Hugging Face Transfer Errors

- Ensure `huggingface_hub` is installed.
- Authenticate if dataset access is gated:

```bash
huggingface-cli login
```

- For upload failures:
  - `Repository Not Found`: create the repo or let the app create it from the prompt.
  - `Revision/Branch Not Found`: create the branch or let the app create it from the prompt.

## Download URL 404 / Not Found

- Verify the repo ID, revision, split, and format in the dialog.
- JSON mode expects `<split>.json`.
- Parquet mode expects a `<split>/` folder.
- If a previously successful URL is now invalid, reselect or correct it in the
  dialog.

## Video Playback Error or Black Screen

Some codecs are not decoded by your platform backend. Convert to H.264/AAC MP4:

```bash
ffmpeg -i input.mp4 -vcodec libx264 -acodec aac output.mp4
```

## No Playback After Selecting a Row

If the selected input is not playable media for the current backend, the row can
stay selected while playback does not start. For example, `frames_npy` and
`tracking_parquet` inputs use specialized renderers, and unsupported text or
metadata files are not played as video.
