# Local and Remote Inference

The application can run models in the local Python process through
OpenSportsLib or use the official OpenSportsLib inference server. All annotation
modes share the same model-selection, queue, review, and error workflow. Remote
inference currently supports Classification and Localization with one or more
videos per sample, and Q/A with exactly one video per sample. Remote Description,
Dense Description, and H5 inference are not available.
VAT pins OpenSportsLib `0.3.1.dev12`, whose remote-only wrappers and public
server model registry are required by this integration.

## Configure inference

Open **Edit → Settings → Inference**. This is the only inference setup
surface; the run dialog never edits models or servers.

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
  on, enter the base URL (default `http://127.0.0.1:8000`) and use **Test
  Connection**. The client calls `/health` and reports API, Redis, worker, and
  configured-model health.
- **Refresh Models** reads the public server registry. The table shows every
  `registering`, `ready`, `failed`, or `unregistering` model and marks task
  defaults; only healthy `ready` models appear in **Run Inference…**. Server
  task `vqa` appears as Q/A.
- **Admin token** is saved in VAT's local application settings when you choose
  **Apply** or **OK**. It is restored the next time Settings or VAT is opened,
  but never enters project JSON or inference requests. VAT's settings storage
  may not encrypt it, so use this only on a trusted workstation; clear the
  field and apply the change to remove it. With a token, **Register Model…** adds
  either a Hugging Face repository or server-local weights/config paths,
  **Set as Default** changes the selected task default, and **Unregister**
  removes a model after confirmation. These actions take effect immediately on
  the external server; cancelling Settings does not undo them. Registration
  and removal are asynchronous, and VAT refreshes transient status every two
  seconds while Settings remains open.
- Server-local paths must be visible to the server and are entered as text; VAT
  deliberately does not open a client-side file picker for them. Shared-root
  and resumable-upload settings from older VAT versions remain ignored.

Connection tests and catalog refreshes use the current unsaved form values.
Only **Apply** or **OK** persists the setup; **Cancel** leaves saved settings
unchanged.

Inference and public registry reads require no authentication. Registry changes
require the server's `OSL_MODEL_ADMIN_TOKEN`. Localhost HTTP is allowed. An HTTP
server on another host is unencrypted, so use it only on a trusted private
network.

## Run inference

Use **Run Inference…** in the **Inference Jobs** dock. The action targets the
currently active annotation mode. Choose a
compatible model and inputs, then fill in the task options shown by the dialog.
The model list combines saved Local models and, when enabled, discovered Remote
models. Entries are prefixed **Local —** or **Remote —**; selecting one chooses
the provider automatically. Local executes OpenSportsLib directly and never
contacts the configured server. Remote constructs the matching
`opensportslib.apis` wrapper and uses its official remote client.

Local Classification and Localization resolve their device in a temporary
per-job configuration; the cached or manually selected model config is never
edited. An `auto` or CUDA configuration falls back to CPU when CUDA is
unavailable. For Localization, if CPU is selected or NVIDIA DALI is
unavailable, DALI dataset types are also replaced with their OpenCV
equivalents. This permits CPU inference with repositories whose training
configuration defaults to CUDA or DALI.

The disposable local Localization config replaces `DATA.common.data_root` and
`DATA.common.splits.test.source_path` with the folder containing the open
dataset JSON. It also points the canonical test split's `annotation_path` to
the generated inference manifest. A model publisher's hardcoded,
machine-specific paths therefore cannot affect the run. The cached or manually
selected source config and the dataset JSON remain unchanged.

Localization predictions are returned relative to the selected inference
inputs. For a UTC-synchronized sample, the application projects them back onto
the whole-sample timeline before saving or displaying them. For example, if a
selected H5 input starts five minutes after the sample's video origin, a model
prediction at H5 position `00:01.250` becomes sample position `05:01.250`.
Offsets are tracked per input: if both video and joints are selected but a
local tracking model actually consumes only the joints/ball H5 inputs, the H5
offset is still applied and the unused video's earlier origin does not suppress
it.
The offset uses an explicit input `UTC_time_start` when present; otherwise,
player H5 inputs use their earliest valid `timestamp_utc` value, even when the
stored timestamp rows are not chronological.

For command-line model checks, `tools/test-inference.py` applies the same basic
principle: it writes a disposable runtime YAML instead of editing the supplied
or Hugging Face-cached config. The runtime YAML replaces publisher-specific
test-data, output, and dataloader-worker defaults. The directory containing the
test JSON is always the data root for relative input paths, and test workers are
fixed at zero. The config's device and GPU fields are preserved so
OpenSportsLib remains the sole device-resolution authority. The tool also
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
annotation panels. The selected head is sent to the server as OSL's `action`
schema and mapped back to the VAT head in results. The request also supplies
the sample ID, FPS, and sample metadata. The last model that completes
successfully is remembered separately for each task. Localization ranges are
clipped locally before upload, and returned positions are translated back to
the original sample timeline using both the clip and input-timeline offsets.

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
cancelling an active Remote job also removes it immediately and starts the next
Remote request. Active Local cancellation remains in `Cancelling` until its
worker exits. The panel retains the latest 20 completed, failed, or cancelled
Local jobs and successful or failed Remote jobs for the current application
session and provides **Clear History**. **Details** shows a bounded, timestamped
timeline of state, progress-stage, cancellation, and error messages.
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

OpenSportsLib wrapper calls are indivisible. Cancelling active Local work leaves
the job in `Cancelling` until the current call returns. Cancelling active Remote
work instead forgets the request immediately: it disappears from the dock and
history, its eventual signals and output are ignored, and the next queued Remote
request starts at once. This is client-side abandonment; the already submitted
server job may continue because the official server has no cancellation endpoint.
A waiting request is cancelled immediately and is never submitted.

Every annotation panel uses the same pending-result footer for Accept/Reject and
bulk review only. Inference execution is centralized in the dock; there are no
task-specific Smart, single-inference, or batch-inference buttons.

## Direct uploads and VQA video reuse

For one-video Classification and Localization requests, media is sent directly
to the official server as multipart form data. For a multi-video sample, VAT
creates a disposable OSL manifest and lets the official client stage and upload
the manifest with all of its media. Q/A remains one-video because a VQA server
session owns one uploaded video. The current OpenSportsLib client buffers direct
files or the staged archive in memory while building the upload request; VAT
does not provide shared-path or resumable-transfer fallbacks. Plan memory use
accordingly for large or multi-view samples.

For the first Q/A question, VAT uploads the video and records the server's
session ID in a private, in-memory cache. Another question for the same server,
model, sample, real video path, file size, and modification time reuses that
session without uploading the video again. Entries expire after 25 minutes.
HTTP 404 or 410 from a reused session causes one automatic fresh upload and
retry. Opening, creating, or closing a project, changing remote-server settings,
or shutting down clears the cache. Session IDs are never stored in project JSON.

Session reuse avoids video transfer only. With the current server, earlier
questions and answers are not conversational context for the model.

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

For Localization, select a confidence-scored row and use the shortcuts configured
under **Edit → Settings → Shortcuts** (`Ctrl+Enter` to accept and
`Ctrl+Backspace` to reject by default). The bindings work only while Localization
is active. After review, selection advances to the next table row, falling back
to the preceding row at the end of the table. A transient rejection remains
non-mutating; accepting, or rejecting a confidence-scored event loaded from JSON,
uses the normal undoable history path.

## Official OpenSportsLib server

VAT uses the FastAPI and RQ server in the OpenSportsLib repository's `server/`
folder. From that repository root, install the server in a Python 3.12+
environment and start its API, Redis, and worker:

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ./server
cd server
bash scripts/setup_env.sh
./scripts/start_all.sh
```

Review `server/.env` before starting it. Set `OSL_MODEL_ADMIN_TOKEN` to enable
VAT's model-management actions; leaving it empty disables administration. The
API and worker must share their Redis queue and runtime directory. VAT uses
these official endpoints without an `/api/v1` prefix:

| Endpoint | VAT use |
|---|---|
| `GET /health` | API, Redis, worker, and configured-model health |
| `GET /models` | Public model IDs, tasks, and lifecycle states |
| `GET /config-capabilities?task_type=…` | Identify each task's current default model |
| `POST /models` | Authenticated Hugging Face or server-local registration |
| `PUT /models/defaults/{task_type}` | Authenticated task-default update |
| `DELETE /models/{model_id}` | Authenticated asynchronous removal |
| `POST /predict` | Multipart video submission or session-based VQA follow-up |
| `GET /jobs/{job_id}` | Poll asynchronous job status |
| `GET /jobs/{job_id}/result` | Retrieve successful OSL predictions |

Single-video Classification and Localization call the official wrapper's
`infer(video_path=..., remote_task_options=...)`. Multi-video samples call
`infer(test_set=..., remote_mode="full_test_set")` with a temporary one-sample
OSL manifest, using the official manifest-and-media upload path. Classification
batches are submitted one sample at a time in queue order. Initial VQA calls
`infer(video_path=..., question=...)` and caches the wrapper's
`last_remote_session_id`; follow-up questions call `infer()` with that session
ID and no video. VAT uses server defaults for advertised inference overrides.

VAT normalizes the returned OSL `data` item into its existing private
`InferenceResult` contract. Request-owned item and sample IDs remain canonical,
`action` is mapped to the selected VAT head, and VQA `answer_text` is mapped to
`answer`. No server job or session identifiers enter the OSL project document.

### Developer architecture and contracts

`InferenceController` remains the queue and worker owner and now also owns the
thread-safe, process-local VQA session cache. It supplies that cache to each
request-scoped `RemoteInferenceProvider`. Project-generation changes and saved
server-setting changes are routed by `MainWindow`, which clears the cache
without exposing it to editor controllers. Shutdown clears it as well.

`RemoteInferenceProvider` is the only official-server adapter. It discovers
models, constructs `ClassificationModel`, `LocalizationModel`, or `VQAModel`
with only `remote=server_url` and `remote_model_id=model_id`. Remote model IDs
are independent of local weights and never trigger local config or Hugging Face
resolution. `ModelDescriptor.status` and `is_default` expose registry state to
Settings; `InferenceRequest`, `InferenceResult`, editor and queue signals,
pending-review behavior, history mutations, and persisted OSL JSON remain
unchanged. Effective acceptance still creates exactly one history entry;
rejection and unreviewed inference create none.

Authenticated registry operations run in a separate controller-owned worker,
one at a time. `MainWindow` is the only cross-module route between Settings and
that worker. The admin token is loaded from and saved to application-local
QSettings, then copied into worker memory only for a registry operation. It
never enters logs, inference requests, or project data. Closing Settings stops
its presentation polling but does not roll back an operation already accepted
by the server.

Network failures and timeouts are retryable `InferenceError`s. HTTP 4xx and
model execution failures are non-retryable, except cached-session HTTP 404/410,
which performs one fresh VQA upload. On Remote cancellation the controller
detaches the blocking worker, removes all request state without adding a history
entry, ignores late signals, and dispatches the next Remote request immediately.
Detached workers are still retained until they exit so their threads can be
cleaned up safely; shutdown waits for them within its normal timeout.

## Local model availability

The installed OpenSportsLib currently exposes `ClassificationModel`,
`LocalizationModel`, and `VQAModel`. Local Description and Dense Description
entries remain visible but disabled until OpenSportsLib supplies native
`DescriptionModel` and `DenseDescriptionModel` APIs. The client does not
approximate these tasks with VQA prompts. The official remote integration also
intentionally leaves Description and Dense Description unavailable.
