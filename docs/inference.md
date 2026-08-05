# Local and Remote Inference

The application can run models in the local Python process through
OpenSportsLib or submit asynchronous jobs to one remote inference server.
Classification, Localization, Description, Dense Description, and Q/A share
the same model-selection, input-selection, progress, cancellation, and error
workflow.

## Configure inference

Open **Edit → Settings → Inference**. This is the only inference setup
surface; the run dialog never edits models, servers, or mappings.

- **Local Models** is an editable registry containing task, model ID, display
  name, config YAML, and optional weights. Fresh installations start with an
  empty registry. Every model is explicitly added and every row can be removed;
  saving an empty registry keeps it empty when Settings is reopened. **Restore
  Defaults** also clears the registry. Retired `jeetv` entries persisted by
  earlier application versions are filtered during loading. The former
  automatically seeded OpenSportsLab rows are also migrated out when they still
  use repository IDs as lazy weights; explicitly imported cache-backed rows are
  retained.
- **Add from Hugging Face…** accepts a repository ID, revision, and optional
  token override. Its editable repository field proposes
  [`OpenSportsLab/OSL-cls-action-mvitv2`](https://huggingface.co/OpenSportsLab/OSL-cls-action-mvitv2),
  [`OpenSportsLab/OSL-loc-snbas-2025-e2e`](https://huggingface.co/OpenSportsLab/OSL-loc-snbas-2025-e2e), and
  [`OpenSportsLab/OSL-loc-snbas-2023-e2e`](https://huggingface.co/OpenSportsLab/OSL-loc-snbas-2023-e2e), but accepts other repositories.
  Blank tokens use the normal Hugging Face login or `HF_TOKEN`.
  Enable **Force re-download cached files** to pass `force_download=True` for
  both files, replacing/re-fetching cached configuration and checkpoint data
  that may have been modified locally.
  The application inspects the repository for an OpenSportsLib `config.yaml`,
  `config.yml`, or `config.json`, selects an unambiguous supported checkpoint,
  and downloads both into the standard Hugging Face cache in a background
  worker. Inline progress and **Cancel Download** keep Settings responsive.
  Cancellation is best-effort during a single Hugging Face file operation, but
  a cancelled result is never inserted. The downloaded row is only a Settings
  draft until **Apply** or **OK**; **Cancel** discards it. **Add Manually**
  remains available for paths already on disk.
- The official `OpenSportsLab/OSL-loc-snbas-2025-e2e` and
  `OpenSportsLab/OSL-loc-snbas-2023-e2e` localization checkpoints use a legacy
  pickle format. Only these exact allowlisted repository identities may opt
  into OpenSportsLib's unsafe legacy deserialization. Changing a model ID,
  repository, revision, or weights path revokes that opt-in; arbitrary Hugging
  Face and manual checkpoints always remain safe-by-default. Only import legacy
  artifacts from sources you trust.
- **Remote Server** has an explicit **Enable remote inference** switch. When it
  is off, discovery and execution never construct an HTTP client. When it is
  on, enter the base URL and use **Test Connection**. The client calls
  `/api/v1/capabilities` and reports the API version and shared-root IDs.
- **Refresh Models** reads the server-owned model catalog into a read-only
  table. Remote models are configured by the server, not edited in the client.
- Add a shared mapping when a local directory and a server storage root contain
  the same files. A file below that directory is sent as
  `shared://<root-id>/<relative-path>` and is not uploaded.

Connection tests and catalog refreshes use the current unsaved form values.
Only **Apply** or **OK** persists the setup; **Cancel** leaves saved settings
unchanged.

Remote v1 has no authentication. Localhost HTTP is allowed. An HTTP server on
another host is marked as unauthenticated and unencrypted; use it only on a
trusted private network.

## Run inference

Use **Run Inference…** in the **Inference Jobs** dock. The action targets the
currently active annotation mode. Choose a
compatible model and inputs, then fill in the task options shown by the dialog.
The model list combines saved Local models and, when enabled, discovered Remote
models. Entries are prefixed **Local —** or **Remote —**; selecting one chooses
the provider automatically. Local executes OpenSportsLib directly and never
contacts the configured server. Remote uses the `/api/v1` API.

Local Classification and Localization resolve their device in a temporary
per-job configuration; the cached or manually selected model config is never
edited. An `auto` or CUDA configuration falls back to CPU when CUDA is
unavailable. For Localization, if CPU is selected or NVIDIA DALI is
unavailable, DALI dataset types are also replaced with their OpenCV
equivalents. This permits CPU inference with repositories whose training
configuration defaults to CUDA or DALI.

For command-line model checks, `tools/test-inference.py` applies the same basic
principle: it writes a disposable runtime YAML instead of editing the supplied
or Hugging Face-cached config. The runtime YAML replaces publisher-specific
test-data, output, and dataloader-worker defaults. The directory containing the
test JSON is always the data root for relative input paths, and test workers are
fixed at zero. The config's device and GPU fields are preserved so
OpenSportsLib dev4 remains the sole device-resolution authority. The tool also
leaves local-checkpoint authentication to OpenSportsLib and always disables
W&B for this minimal inference workflow. Every run requires either `--config`
or `--hf-model`, plus `--output`; batch runs also require `--test-set`.

Instead of passing cached paths explicitly, `--hf-model owner/repository`
inspects the Hugging Face model repository and downloads its supported
OpenSportsLib config and checkpoint into the standard Hugging Face cache before
running inference. `--hf-revision` selects a branch, tag, or commit;
`--force-download` refreshes both cached artifacts. Private or gated models can
use `--hf-token`, although `HF_TOKEN` or a saved Hugging Face login avoids
putting a token in shell history. `--hf-model` cannot be combined with
`--config` or `--weights`, and the downloaded config task must match `--task`.

For VQA, `--question` is required and is applied to every sample in
`--test-set`. The script writes a temporary annotation file containing that
question for each sample, then makes one `VQAModel.infer(test_set=...)` call so
the model is loaded only once. OpenSportsLib uses the first video input in each
sample; relative paths are resolved from the directory containing the original
JSON. Existing answers in the source JSON are not modified on disk.

For example:

```bash
python tools/test-inference.py \
  --task classification \
  --hf-model OpenSportsLab/OSL-cls-action-mvitv2 \
  --force-download \
  --test-set /path/to/annotations_test.json \
  --output /path/to/annotations_test-pred.json
```

For example, run the Qwen 2.5 VQA adapter with:

```bash
python tools/test-inference.py \
  --task vqa \
  --hf-model OpenSportsLab/OSL-VQA-XFOUL-qwen2.5-7B-VL-lora \
  --test-set /path/to/annotations_test.json \
  --question "Is this a foul, and why?" \
  --output /path/to/annotations_test-vqa-pred.json
```

The same command supports
`OpenSportsLab/OSL-VQA-XFOUL-qwen3-8B-VL-lora` and
`OpenSportsLab/OSL-VQA-XFOUL-XVARS-lora`. The X-VARS adapter additionally
requires its separately published base Video-ChatGPT bundle and visual encoder
checkpoint; update a local config or place those artifacts beside its cached
config as described below.

Local VQA likewise uses a temporary writable output directory and resolves
`auto`/CUDA to CPU when necessary. OpenSportsLib 0.3 `answer_text` results are
normalized into the annotation tool's answer field. X-VARS LoRA repositories
contain adapters rather than every base artifact: local inference also requires
the `base_model_videoChatGPT` directory and `14_model.pth.tar`. If the published
config contains stale absolute paths, place these artifacts beside its local
`config.yaml` or point a local config copy at them. Missing dependencies are
reported as `local_model_dependency_missing`; publisher paths such as
`/home/vorajv` are never used as writable output locations.

The dialog lists only runnable models for the current task. Setup problems are
reported briefly and corrected in application Settings. It contains runtime
options only: Classification scope, compatible inputs, language or question
where applicable, and time ranges only for models that support ranges.
Classification and Localization use the head already selected in their
annotation panels. The last model that completes successfully is remembered
separately for each task. Localization range uploads are clipped locally when
shared storage is unavailable, and returned positions are translated back to
the original sample timeline.

Classification exposes current-sample and all-samples scope in this dialog; it
does not have a separate batch-inference control. Its input list shows only the
currently selected sample. For all-samples scope, that input selection is used
as the positional modality template for every sample in the batch.

## Background execution

Inference uses two session-only FIFO queues: one for Local models and one for
Remote models. Each queue runs one job at a time, while one Local and one Remote
job may run concurrently. Additional **Run Inference…** actions remain available
and append work to the selected model's provider queue. Local providers and
Remote uploads/jobs are not created until their request reaches the front.

The dock is placed below the Annotation Editor and is available from
**View → Inference Jobs**. It opens automatically when work is queued and is
raised when a job fails. It hides with the other project docks when returning
to the welcome screen, where its View action is disabled. Its previous visible
or hidden preference is restored when a project workspace is shown again. The
application status bar remains reserved for normal
status messages. The dock shows both lanes, active and waiting jobs, progress,
per-job **Cancel**, and **Cancel All**. Cancelling a waiting job removes it immediately;
cancelling an active job remains `Cancelling` until its worker exits. The panel
retains the latest 20 completed, failed, or cancelled jobs for the current
application session and provides **Clear History**. **Details** shows a bounded,
timestamped timeline of state, progress-stage, cancellation, and error messages.
Dataset navigation, playback, editing, saving, and tab switching remain
available throughout.

Each request captures its original project generation, sample IDs, task head or
question, and request-item IDs. Results are correlated back to those immutable
request items and never to the sample currently visible when the model finishes.
Navigating from sample A to sample B therefore leaves A's predictions pending;
they appear when A is selected again and its Smart Labelled status updates in
the explorer. Completion never changes the currently selected annotation mode,
Classification head, or Localization head. Removed or renamed sample targets are discarded rather than
redirected. Opening, creating, or closing a project cancels both active jobs,
discards both waiting queues, and suppresses late results from the previous
project.

Remote jobs can usually be cancelled during upload or polling. Local
OpenSportsLib calls may be indivisible, so cancellation can take effect only
after the current library call returns; its late output is still suppressed.
Queued Remote work is not submitted to the server before it becomes active.

Every annotation panel uses the same pending-result footer for Accept/Reject and
bulk review only. Inference execution is centralized in the dock; there are no
task-specific Smart, single-inference, or batch-inference buttons.

## Large files

The client resolves each input in this order:

1. A configured shared-storage mapping.
2. A previously completed upload for the same server, path, size, and modified
   time.
3. A resumable multipart upload.

Multipart state is application state, not project JSON. The server chooses the
part size. The client uploads up to three parts concurrently, streams each part
in bounded chunks, sends a SHA-256 checksum, retries transient failures up to
five times, and records completed ETags/checksums. Restarting asks the server
which parts already exist. Cancelling aborts the active job and an incomplete
active upload.

## Review predictions

- Classification shows the proposed label beside its head.
- Localization and Dense Description show visually distinct pending rows.
- Description previews the candidate without changing the caption list; acceptance
  appends a new caption and rejection is non-mutating.
- Q/A shows a pending answer under the selected or newly entered question.

Predictions remain in session memory until accepted. They do not dirty the
project, enter exported JSON, or create undo entries. **Accept** commits a
plain annotation as one undoable mutation; **Reject** only removes the pending
candidate. Multi-result widgets also provide **Accept All** and **Reject All**.
Pending rows show confidence and model identity, and the Smart Labelled filter
recognizes them while the application is open. Editing the same annotation
manually invalidates its pending candidates.

## Server API v1

The client expects these JSON endpoints below `/api/v1`:

| Endpoint | Purpose |
|---|---|
| `GET /capabilities` | API version, tasks, polling interval, multipart limits, shared roots |
| `GET /models?task=…` | Task-compatible model descriptors |
| `POST /uploads` | Create or deduplicate a multipart upload |
| `GET /uploads/{id}` | Resume state and refreshed part URLs |
| `POST /uploads/{id}/complete` | Complete parts and return an asset ID |
| `DELETE /uploads/{id}` | Abort an incomplete upload |
| `POST /jobs` | Create an idempotent asynchronous inference job |
| `GET /jobs/{id}` | Poll status and retrieve an inline result |
| `GET /jobs/{id}/result` | Retrieve a non-inline successful result |
| `DELETE /jobs/{id}` | Cancel a job |

Model descriptors use `id`, `display_name`, `task`, `version`, `available`,
`unavailable_reason`, `accepted_input_types`, `min_inputs`, `max_inputs`, and
`supports_time_range`.

Jobs receive `idempotency_key`, `model_id`, `task`, `schema`, `parameters`, and
`items`. Each item has `item_id`, `sample_id`, and inputs whose asset is either
`{"kind":"shared","uri":"shared://…"}` or
`{"kind":"upload","id":"…"}`. Job states are `queued`, `running`,
`succeeded`, `failed`, and `cancelled`. Errors use `code`, `message`, `details`,
and `retryable`; polling may return `Retry-After`.

Successful result items use the task-native field: `labels`, `events`,
`captions`, `dense_captions`, or `answer`. Remote results must return the
request's `item_id` (or a unique request `sample_id` for compatibility). The
server returns exactly one result item per request item. The client rejects
missing, excess, unknown, and duplicate result targets and replaces result-owned
sample IDs with the canonical request mapping.

The Flask application should be a control plane behind a production WSGI
server/reverse proxy. Model execution belongs in durable workers. Large media
should go to S3-compatible multipart storage or an equivalent chunk store, not
through one long-running Flask multipart request.

## Local model availability

The installed OpenSportsLib currently exposes `ClassificationModel`,
`LocalizationModel`, and `VQAModel`. Local Description and Dense Description
entries remain visible but disabled until OpenSportsLib supplies native
`DescriptionModel` and `DenseDescriptionModel` APIs. The client does not
approximate these tasks with VQA prompts. Remote models for those tasks remain
fully available.
