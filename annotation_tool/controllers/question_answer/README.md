# Question/Answer Controller

## Role
Owns Question/Answer mode behavior:
- shared dataset-level question bank actions (add/rename/delete)
- per-sample multiline answer editing with autosave
- emits typed mutation intents to `HistoryManager`

## Contracts
- Constructor accepts only panel dependency.
- Does not mutate dataset directly.
- Uses sparse `answers` payloads (`question_id`, `answer`) with non-empty answers only.
