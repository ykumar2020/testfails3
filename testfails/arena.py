from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .util import now_iso, sha256_value, write_json


DATASET = "lmarena-ai/leaderboard-dataset"
DATASET_CARD = "https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset"
ROWS_API = "https://datasets-server.huggingface.co/rows"
BOARDS = {
    "text": "text_style_control",
    "agent": "agent",
    "search": "search_style_control",
    "webdev": "webdev",
}


def _fetch(config: str, length: int = 100) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {"dataset": DATASET, "config": config, "split": "latest", "offset": 0, "length": length}
    )
    request = urllib.request.Request(
        f"{ROWS_API}?{query}", headers={"User-Agent": "testFAILS3/0.1 (+https://github.com/ykumar2020/testfails3)"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.load(response)
    return [item["row"] for item in body.get("rows", [])]


def sync_arena(destination: Path) -> dict[str, Any]:
    boards: dict[str, Any] = {}
    errors: list[dict[str, str]] = []
    for label, config in BOARDS.items():
        try:
            rows = _fetch(config)
            overall = [row for row in rows if row.get("category") == "overall"]
            selected = overall or rows
            selected.sort(key=lambda row: (row.get("rank") is None, row.get("rank", 10_000)))
            boards[label] = {
                "config": config,
                "publishDate": selected[0].get("leaderboard_publish_date") if selected else None,
                "rows": selected[:25],
            }
        except Exception as exc:  # a failed upstream must remain visible
            errors.append({"board": label, "error": f"{type(exc).__name__}: {exc}"})
        time.sleep(0.05)
    document = {
        "schemaVersion": 1,
        "source": DATASET_CARD,
        "api": ROWS_API,
        "retrievedAt": now_iso(),
        "license": "CC BY 4.0",
        "boards": boards,
        "errors": errors,
    }
    document["sha256"] = sha256_value(document)
    if not boards:
        raise RuntimeError(f"Arena synchronization returned no boards: {errors}")
    write_json(destination, document)
    return document


def load_arena(path: Path, refresh_after_seconds: int = 21_600) -> dict[str, Any]:
    saved: dict[str, Any] = {}
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
    try:
        stamp = saved.get("retrievedAt", "")
        age = (datetime.now(UTC) - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds()
    except (TypeError, ValueError):
        age = refresh_after_seconds + 1
    if age <= refresh_after_seconds:
        return saved
    try:
        # Serverless filesystems may be read-only. Fetching is still real; persistence is best-effort.
        boards: dict[str, Any] = {}
        errors: list[dict[str, str]] = []
        for label, config in BOARDS.items():
            try:
                rows = _fetch(config)
                overall = [row for row in rows if row.get("category") == "overall"]
                selected = overall or rows
                selected.sort(key=lambda row: (row.get("rank") is None, row.get("rank", 10_000)))
                boards[label] = {"config": config, "publishDate": selected[0].get("leaderboard_publish_date") if selected else None, "rows": selected[:25]}
            except Exception as exc:
                errors.append({"board": label, "error": f"{type(exc).__name__}: {exc}"})
        if boards:
            live = {"schemaVersion": 1, "source": DATASET_CARD, "api": ROWS_API, "retrievedAt": now_iso(), "license": "CC BY 4.0", "boards": boards, "errors": errors}
            live["sha256"] = sha256_value(live)
            return live
    except Exception:
        pass
    return saved
