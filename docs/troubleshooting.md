# Troubleshooting

## App Fails To Start

- Confirm your environment is active.
- Reinstall dependencies:

```bash
pip install -r requirements.txt
```

## Hugging Face Transfer Errors

- Ensure `huggingface_hub` is installed.
- Authenticate if dataset access is gated:

```bash
huggingface-cli login
```

- For upload failures:
  - `Repository Not Found`: create repo or let the app create it from the prompt.
  - `Revision/Branch Not Found`: create branch or let the app create it from the prompt.

## Download URL 404 / Not Found

- Verify the URL points to the intended file or folder in the dataset repo.
- If a previously successful URL is now invalid, reselect/correct it in the dialog.

## Video Playback Error Or Black Screen

Some codecs are not decoded by your platform backend. Convert to H.264/AAC MP4:

```bash
ffmpeg -i input.mp4 -vcodec libx264 -acodec aac output.mp4
```

## No Playback After Selecting A Row

If the selected input is non-video (for example text metadata), this is expected: the row stays selectable but media playback is not started.
