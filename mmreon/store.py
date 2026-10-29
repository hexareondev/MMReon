"""Журнал матчей и последнего известного рейтинга в data/matches.json."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {"version": 1, "rating": None, "matches": []}

    @property
    def matches(self) -> list:
        return self.data["matches"]

    @property
    def rating(self) -> dict | None:
        return self.data["rating"]

    @rating.setter
    def rating(self, value: dict):
        self.data["rating"] = value

    def find(self, match_id: str) -> dict | None:
        return next((m for m in self.matches if m["match_id"] == match_id), None)

    def pending(self) -> list:
        return [m for m in self.matches if m["status"] == "pending"]

    def save(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
