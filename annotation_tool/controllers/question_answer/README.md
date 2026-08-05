# Question/Answer Controller

## Role
Owns Question/Answer mode behavior:
- per-sample grouped question/answer editing with autosave
- dataset-derived question suggestions for add/edit dialogs
- multiline answer add/edit dialogs
- emits typed mutation intents to `HistoryManager`

Shared VQA inference answers the selected question. Pending answers are
session-only `{text, confidence_score, inference_model_id}` candidates; accept stores
a manual string and reject removes it. Readers accept both forms.

## Contracts
- Constructor accepts only panel dependency.
- Does not mutate dataset directly.
- Uses grouped `answers` payloads (`question`, `answers[]`) with non-empty answers only.
- Local execution remains provider-owned: it rewrites only a temporary config,
  validates external X-VARS base/vision artifacts before model allocation, and
  normalizes OpenSportsLib 0.3 `answer_text` payloads.
