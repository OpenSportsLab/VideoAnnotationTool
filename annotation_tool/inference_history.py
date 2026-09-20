"""SQLite storage for terminal inference job metadata and bounded event logs."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict

from PyQt6.QtCore import QStandardPaths

from inference_types import InferenceLogEvent, InferenceQueueEntry


class InferenceHistoryStore:
    def __init__(self, path: str | None = None):
        app_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )
        self.path = path or os.path.join(app_dir, "inference_history.sqlite3")
        self._connection: sqlite3.Connection | None = None
        self.error = ""
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            self._connection = sqlite3.connect(self.path)
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS inference_jobs (
                    request_id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    provider_name TEXT NOT NULL,
                    backend TEXT NOT NULL,
                    task TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    sample_ids_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    message TEXT NOT NULL,
                    current INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    submitted_at REAL NOT NULL,
                    started_at REAL NOT NULL,
                    finished_at REAL NOT NULL,
                    error_code TEXT NOT NULL,
                    error_details_json TEXT,
                    retryable INTEGER NOT NULL,
                    log_events_json TEXT NOT NULL
                )
                """
            )
            self._connection.commit()
        except Exception as exc:
            self.error = f"Inference history is session-only: {exc}"
            self.close()

    def load(self) -> list[InferenceQueueEntry]:
        if self._connection is None:
            return []
        try:
            rows = self._connection.execute(
                "SELECT * FROM inference_jobs ORDER BY finished_at ASC"
            ).fetchall()
            columns = [item[0] for item in self._connection.execute(
                "SELECT * FROM inference_jobs LIMIT 0"
            ).description]
            entries = []
            for row in rows:
                value = dict(zip(columns, row))
                events = tuple(
                    InferenceLogEvent(**event)
                    for event in json.loads(value.pop("log_events_json") or "[]")
                )
                entries.append(InferenceQueueEntry(
                    request_id=value["request_id"],
                    backend=value["backend"],
                    task=value["task"],
                    model_id=value["model_id"],
                    sample_ids=tuple(json.loads(value["sample_ids_json"] or "[]")),
                    state=value["state"],
                    message=value["message"],
                    current=value["current"],
                    total=value["total"],
                    submitted_at=value["submitted_at"],
                    started_at=value["started_at"],
                    finished_at=value["finished_at"],
                    error_code=value["error_code"],
                    error_details=json.loads(value["error_details_json"] or "null"),
                    retryable=bool(value["retryable"]),
                    log_events=events,
                    provider_id=value["provider_id"],
                    provider_name=value["provider_name"],
                ))
            return entries
        except Exception as exc:
            self.error = f"Inference history is session-only: {exc}"
            self.close()
            return []

    def append(self, entry: InferenceQueueEntry) -> None:
        if self._connection is None:
            return
        try:
            self._connection.execute(
                """INSERT OR REPLACE INTO inference_jobs VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.request_id, entry.provider_id, entry.provider_name,
                    entry.backend, entry.task, entry.model_id,
                    json.dumps(entry.sample_ids), entry.state, entry.message,
                    entry.current, entry.total, entry.submitted_at, entry.started_at,
                    entry.finished_at, entry.error_code,
                    json.dumps(entry.error_details, default=str), int(entry.retryable),
                    json.dumps([asdict(event) for event in entry.log_events], default=str),
                ),
            )
            self._connection.commit()
        except Exception as exc:
            self.error = f"Inference history is session-only: {exc}"
            self.close()

    def clear(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.execute("DELETE FROM inference_jobs")
            self._connection.commit()
        except Exception as exc:
            self.error = f"Could not clear inference history: {exc}"

    def close(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


__all__ = ["InferenceHistoryStore"]
