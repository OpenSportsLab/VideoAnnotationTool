# Video Annotation Tool

The Video Annotation Tool is a PyQt6 desktop application for loading, editing, and exporting OSL-style sports-video datasets.

![Main GUI Screenshot](assets/dense-description-UI.png)

## What You Can Do

- Create, open, close, save, and export dataset JSON projects.
- Manage samples and multi-input clips from the Dataset Explorer.
- Annotate across five modes:
  - Classification (`labels`)
  - Localization (`events`)
  - Description (`captions`)
  - Dense Description (`dense_captions`)
  - Question/Answer (`answers`)
- Use global undo/redo for tracked edits.
- Preserve absolute Localization and Dense Description times while modalities
  are added, removed, filtered, or resynchronized.
- Download from and upload to Hugging Face from the **Data** menu.
- Run local OpenSportsLib models or asynchronous remote inference jobs with
  resumable large-file transfer and smart-result review.

## Quick Links

- [Installation](installation.md)
- [Getting Started](getting_started.md)
- [GUI Overview](gui_overview.md)
- [Synchronized Multi-Modality Playback](synchronized_playback.md)
- [Batch Tools](batch_tools.md)
- [Local and Remote Inference](inference.md)
- [OSL JSON Format](OSL.md)
- [FAQ](faq.md)

## License

This project is dual-licensed:

- **AGPL-3.0** (see `LICENSE`)
- **Commercial license** (see `LICENSE_COMMERCIAL`)
