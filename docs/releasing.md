# Release Guide

This project publishes standalone Windows, macOS, and Linux builds through
`.github/workflows/release.yml`. Pushing a tag named `v*` or `V*` creates a
public GitHub Release, generates notes from the latest 20 commit subjects, and
uploads the platform ZIP files.

## Prerequisites

- Use the canonical lowercase tag format `vMAJOR.MINOR.PATCH`, for example
  `v1.4.4`.
- Start from a clean `main` branch synchronized with `origin/main`.
- Confirm the intended version does not already exist locally or remotely.
- Confirm the current `main` CI and documentation workflows are successful.
- Ensure Git can push to `origin`. GitHub CLI authentication is optional; it is
  useful for monitoring but is not required when Git HTTPS credentials work.
- Never paste a GitHub token into chat or commit it to the repository. Repair
  GitHub CLI access locally with `gh auth login -h github.com` when needed.

## Prepare the release commit

1. Change `APP_VERSION` in `annotation_tool/app_info.py` to the new tag value,
   including the leading `v`.
2. Run the relevant test suites and release checks:

   ```bash
   python -m pytest -q tests/gui
   python -m py_compile annotation_tool/app_info.py
   git diff --check
   ```

3. Commit only the version bump:

   ```bash
   git add annotation_tool/app_info.py
   git commit -m "chore: Bump version to vMAJOR.MINOR.PATCH"
   ```

4. Land the commit on `main` through the repository's normal pull-request
   policy. A maintainer may push directly only when intentionally using their
   branch-rule bypass permission.
   
5. Wait for the `main` workflows to complete successfully before tagging.

## Publish

Existing releases use lightweight tags. Tag the exact version commit and push
only that tag:

```bash
git tag vMAJOR.MINOR.PATCH
git show -s --format='%H %s' vMAJOR.MINOR.PATCH
git push origin vMAJOR.MINOR.PATCH
```

The tag push starts **Build and Release Standalone GUI**. The release record is
created before the platform builds finish, so an initially empty asset list is
normal. Builds commonly take 10–15 minutes, with Windows sometimes completing
last.

## Verify completion

Do not consider the release complete until the workflow succeeds and all three
non-empty assets appear on the release:

- `VideoAnnotationTool-win.zip`
- `VideoAnnotationTool-mac.zip`
- `VideoAnnotationTool-linux.zip`

Each uploaded asset should report a SHA-256 digest. Also verify that local and
remote tags resolve to the intended commit:

```bash
git rev-parse vMAJOR.MINOR.PATCH
git ls-remote --tags origin refs/tags/vMAJOR.MINOR.PATCH
```

With an authenticated GitHub CLI, monitor and inspect the release with:

```bash
gh run list --workflow release.yml --branch vMAJOR.MINOR.PATCH
gh release view vMAJOR.MINOR.PATCH
```

The public release is available at:

```text
https://github.com/OpenSportsLab/VideoAnnotationTool/releases/tag/vMAJOR.MINOR.PATCH
```

## Failure handling

- For a transient runner or upload failure, rerun only the failed GitHub Actions
  jobs and verify all three assets afterward.
- If released code needs a correction, prefer a new patch release rather than
  moving or replacing a published tag.
- Do not delete a release, overwrite assets, or force-move a tag without an
  explicit maintainer decision; those actions invalidate published references
  and checksums.

