# Annotating

## Classification

1. Select a sample in the Dataset Explorer.
2. Open `CLS`.
3. Choose labels in each head.
4. Changes persist immediately when they are effective.

## Localization

1. Select a sample and open `LOC`.
2. Use spotting buttons to add events at current time.
3. Edit or delete events from the event table.
4. Optional: run smart inference for a selected head.

## Description

1. Select a sample and open `DESC`.
2. Edit caption text.
3. Autosave stores the caption in `captions`.

## Dense Description

1. Select a sample and open `DENSE`.
2. Click **Add New Description**.
3. Enter text in the modal; event is stored at current `position_ms`.
4. Edit time/text from the table when needed.

## Question/Answer

1. Open `Q/A`.
2. Add or select a question tab.
3. Enter the sample answer.
4. Answers are stored as sparse `answers` keyed by `question_id`.
