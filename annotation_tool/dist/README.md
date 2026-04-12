# Deploy Guide

This document is for maintainers who want to build, validate, and publish standalone executables for VideoAnnotationTool.

If you only want to run the app from source, use the instructions in [README.md](../../README.md) and [docs/installation.md](../../docs/installation.md).

## Source Of Truth

There are two GitHub Actions workflows related to executable builds:

- [.github/workflows/ci.yml](../../.github/workflows/ci.yml)
  Branch/manual build workflow that produces artifacts.
- [.github/workflows/release.yml](../../.github/workflows/release.yml)
  Tag-triggered release workflow that creates GitHub Releases and uploads platform binaries.

For local macOS builds, use the macOS job in [release.yml](../../.github/workflows/release.yml) as the canonical command sequence. It matches the packaging used for published releases.

## What Gets Bundled

The packaged app must include these runtime assets from [annotation_tool](..):

- `style/`
- `ui/`
- `controllers/`
- `image/`
- `config.yaml`
- `loc_config.yaml`

The workflows also collect package data for:

- `opensportslib`
- `lightning_fabric`
- `wandb`
- `torch_geometric`

These flags are required because the older build snippet in [README.md](../../README.md) is incomplete relative to the current workflows.

## Prerequisites

Use the same assumptions as the workflows:

- macOS
- Python `3.12`
- Working directory starts at the repository root
- Dependencies installed from [requirements.txt](../../requirements.txt)

Recommended setup:

```bash
conda create -n VideoAnnotationTool python=3.12 -y
conda activate VideoAnnotationTool
pip install -r requirements.txt
```

If you are validating a release candidate, it is also reasonable to run the GUI tests first:

```bash
pytest tests/gui/test_*.py
```

## Local macOS Build

This is the closest local equivalent to the macOS job in [release.yml](../../.github/workflows/release.yml).

From the repository root:

```bash
cd annotation_tool

rm -rf build dist *.spec
pip cache purge || true

python -m pip install --upgrade pip
pip install -r ../requirements.txt

python -m PyInstaller --noconfirm --clean --windowed \
  --name "VideoAnnotationTool" \
  --add-data "style:style" \
  --add-data "ui:ui" \
  --add-data "controllers:controllers" \
  --add-data "image:image" \
  --add-data "config.yaml:." \
  --add-data "loc_config.yaml:." \
  --collect-all "opensportslib" \
  --collect-all "lightning_fabric" \
  --collect-all "wandb" \
  --collect-all "torch_geometric" \
  "main.py"
```

Expected output:

- `annotation_tool/dist/VideoAnnotationTool.app`

To package it exactly like the release workflow does:

```bash
ditto -c -k --sequesterRsrc --keepParent \
  "dist/VideoAnnotationTool.app" \
  "dist/VideoAnnotationTool-mac.zip"
```

Expected zip output:

- `annotation_tool/dist/VideoAnnotationTool-mac.zip`

## Validate The macOS App Locally

After the build finishes:

1. Launch the `.app` bundle directly from Finder or Terminal.
2. Verify the main window opens.
3. Open a small sample dataset and verify media loads.
4. Check that classification and localization views open without missing resource/config errors.
5. If you are validating inference-related packaging, run at least one classification inference and one localization inference.

You can launch from Terminal with:

```bash
open "annotation_tool/dist/VideoAnnotationTool.app"
```

If macOS blocks the app because it is unsigned, clear quarantine on the locally built or downloaded bundle:

```bash
xattr -dr com.apple.quarantine "annotation_tool/dist/VideoAnnotationTool.app"
```

This repository does not currently implement code signing or notarization in GitHub Actions.

## Release Workflow

The release workflow is defined in [release.yml](../../.github/workflows/release.yml).

Trigger conditions:

- Push a tag matching `v*`
- Push a tag matching `V*`

What it does:

1. Generates release notes from the last 20 commit subjects.
2. Creates or updates the GitHub Release.
3. Builds Windows, macOS, and Linux binaries.
4. Uploads zipped artifacts to the GitHub Release.

Typical release flow:

```bash
git checkout main
git pull
git tag V1.2.0
git push origin V1.2.0
```

Use whatever versioning convention your project currently follows, but the tag must match `v*` or `V*`.

## CI Build Workflow

The artifact-only workflow is [ci.yml](../../.github/workflows/ci.yml).

It runs on:

- pushes to selected branches
- manual `workflow_dispatch`

It builds the same platform binaries, but uploads them as workflow artifacts instead of GitHub Release assets.

## Cross-Platform Reference

These commands are mirrors of the current workflows and are included here for reference.

### Windows

The Windows workflow uses `--onefile` and PowerShell syntax.

Important: Windows `--add-data` must use `;` as the separator.

```powershell
cd annotation_tool

python -m PyInstaller --noconfirm --clean --windowed --onefile `
  --name "VideoAnnotationTool" `
  --add-data "style;style" `
  --add-data "ui;ui" `
  --add-data "controllers;controllers" `
  --add-data "image;image" `
  --add-data "config.yaml;." `
  --add-data "loc_config.yaml;." `
  --collect-all "opensportslib" `
  --collect-all "lightning_fabric" `
  --collect-all "wandb" `
  --collect-all "torch_geometric" `
  "main.py"
```

### Linux

The Linux workflow uses `--onefile` and requires runtime system packages in CI.

```bash
cd annotation_tool

python -m PyInstaller --noconfirm --clean --windowed --onefile \
  --name "VideoAnnotationTool" \
  --add-data "style:style" \
  --add-data "ui:ui" \
  --add-data "controllers:controllers" \
  --add-data "image:image" \
  --add-data "config.yaml:." \
  --add-data "loc_config.yaml:." \
  --collect-all "opensportslib" \
  --collect-all "lightning_fabric" \
  --collect-all "wandb" \
  --collect-all "torch_geometric" \
  "main.py"
```

## Known Notes

- The build section in [README.md](../../README.md) currently omits several required assets and `--collect-all` flags. Use this document and the workflow files as the source of truth.
- Localization inference needs `lightning_fabric` package data in the bundled app. If you built the app before this flag was added, delete `annotation_tool/dist` and rebuild.
- [docs/installation.md](../../docs/installation.md) still contains an older Python `3.9` example, while the workflows use Python `3.12`.
- The workflow name referenced in older docs as `CL.yml` is now [ci.yml](../../.github/workflows/ci.yml).
- In [ci.yml](../../.github/workflows/ci.yml), the Windows `loc_config.yaml` `--add-data` flag currently uses `:` instead of `;`. For local Windows builds, use `;` consistently.

## Suggested Maintainer Checklist

Before tagging a release:

1. Run the relevant GUI tests.
2. Build the macOS app locally using the command above.
3. Launch the built `.app` and sanity-check the main workflows.
4. Confirm the version tag you plan to push.
5. Push the tag and verify release assets appear on GitHub.
