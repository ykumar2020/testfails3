from __future__ import annotations

import base64
import json
import re
import struct
import zlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .assertions import AssertionEngine
from .util import sha256_value

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path(__file__).with_name("suite_manifest.json")
JSON_ONLY = "Return only a valid JSON object. Do not use Markdown fences."


class TestCase(BaseModel):
    __test__ = False
    case_id: str
    dimension: str
    component: str
    title: str
    prompt_template: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_assertions: list[dict[str, Any]]
    modality: str = "text"
    image_fixture: str | None = None
    seed: int
    notes: str = ""

    @property
    def id(self) -> str:
        return self.case_id

    @property
    def prompt(self) -> str:
        return self.render_prompt()

    @property
    def assertions(self) -> list[dict[str, Any]]:
        return self.expected_assertions

    def render_prompt(self) -> str:
        return self.prompt_template.format(**self.parameters)

    def compute_prompt_hash(self) -> str:
        return sha256_value(self.render_prompt())


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def benchmark_image_data_url() -> str:
    """Return the retained deterministic 8x4 sanity PNG: red left, blue right."""
    width, height = 8, 4
    rows = [b"\x00" + b"\xff\x00\x00" * 4 + b"\x00\x00\xff" * 4 for _ in range(height)]
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += _png_chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
    png += _png_chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def image_data_url(case: TestCase) -> str | None:
    if not case.image_fixture:
        return None
    if case.image_fixture == "builtin:color-block-8x4":
        return benchmark_image_data_url()
    path = (ROOT / case.image_fixture).resolve()
    fixtures_root = (ROOT / "fixtures").resolve()
    if fixtures_root not in path.parents or not path.is_file():
        raise ValueError(f"invalid image fixture: {case.image_fixture}")
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.casefold())
    if not mime:
        raise ValueError(f"unsupported image fixture type: {path.suffix}")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _resolve(value: Any, parameters: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$param"}:
            return parameters[value["$param"]]
        return {key: _resolve(item, parameters) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, parameters) for item in value]
    if isinstance(value, str):
        try:
            return value.format(**parameters)
        except (KeyError, ValueError):
            return value
    return value


@lru_cache(maxsize=1)
def raw_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def cases() -> list[TestCase]:
    raw = raw_manifest()
    frozen = raw["frozen_evaluation_date"]
    output: list[TestCase] = []
    for dimension in raw["dimensions"]:
        probes = dimension.get("probes", [])
        required = int(raw["probe_policy"]["minimum_probes_per_dimension"])
        if len(probes) < required:
            raise ValueError(f"dimension {dimension['id']} has {len(probes)} probes; requires {required}")
        for index, probe in enumerate(probes, start=1):
            parameters = {
                "json_only": JSON_ONLY,
                "frozen_evaluation_date": frozen,
                **probe.get("parameters", {}),
            }
            output.append(TestCase(
                case_id=f"{dimension['id']}-{index:02d}",
                dimension=dimension["id"],
                component=dimension["component"],
                title=dimension["title"],
                prompt_template=dimension["prompt_template"],
                parameters=parameters,
                expected_assertions=_resolve(dimension["assertions"], parameters),
                modality="image" if probe.get("image_fixture") else "text",
                image_fixture=probe.get("image_fixture"),
                seed=int(probe["seed"]),
                notes=dimension.get("notes", ""),
            ))
    identifiers = [case.case_id for case in output]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("suite contains duplicate case identifiers")
    return output


def _fixture_hash(case: TestCase) -> str | None:
    data_url = image_data_url(case)
    return sha256_value(data_url) if data_url else None


def suite_manifest() -> dict[str, Any]:
    raw = raw_manifest()
    expanded = [
        {
            "id": case.case_id,
            "dimension": case.dimension,
            "component": case.component,
            "title": case.title,
            "modality": case.modality,
            "seed": case.seed,
            "promptTemplate": case.prompt_template,
            "parameters": case.parameters,
            "renderedPrompt": case.render_prompt(),
            "promptHash": case.compute_prompt_hash(),
            "imageFixture": case.image_fixture,
            "fixtureHash": _fixture_hash(case),
            "assertions": case.expected_assertions,
        }
        for case in cases()
    ]
    dimensions = [
        {
            "id": item["id"],
            "component": item["component"],
            "title": item["title"],
            "probeCount": len(item["probes"]),
        }
        for item in raw["dimensions"]
    ]
    hash_payload = {
        "name": raw["name"],
        "version": raw["version"],
        "frozenEvaluationDate": raw["frozen_evaluation_date"],
        "probePolicy": raw["probe_policy"],
        "cases": expanded,
    }
    return {
        **hash_payload,
        "dimensionCount": len(dimensions),
        "dimensions": dimensions,
        "caseCount": len(expanded),
        "sha256": sha256_value(hash_payload),
    }


def parse_json_response(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise TypeError("response is not a JSON object")
    return parsed


def evaluate_assertion(document: dict[str, Any], assertion: dict[str, Any]) -> tuple[bool, str]:
    """Compatibility helper; new execution should use AssertionEngine directly."""
    result = AssertionEngine().evaluate(document, [assertion])[0]
    return result.passed, result.details or result.mode
