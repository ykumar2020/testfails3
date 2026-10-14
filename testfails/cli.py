from __future__ import annotations

import argparse
import os
from pathlib import Path

from .arena import sync_arena
from .providers import configured_providers
from .runner import run_all


ROOT = Path(__file__).resolve().parents[1]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser(description="testFAILS3 autonomous evaluation")
    parser.add_argument("command", choices=("sync-arena", "evaluate", "all"))
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    if args.command in {"sync-arena", "all"}:
        result = sync_arena(ROOT / "data" / "arena_latest.json")
        print(f"Arena: {len(result['boards'])} boards, {len(result['errors'])} errors, {result['retrievedAt']}")
    if args.command in {"evaluate", "all"}:
        providers = configured_providers()
        if not providers:
            print("No provider credentials configured; no model run was created.")
            return 2
        run = run_all(providers, ROOT / "data" / "runs")
        for model in run["models"]:
            print(f"{model['provider']}/{model['model']}: score={model['score']} coverage={model['coverage']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
