from __future__ import annotations

import json
import platform
import statistics
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .assertions import AssertionEngine
from .benchmarks import cases, image_data_url, parse_json_response, suite_manifest
from .providers import ProviderError
from .status import COMPLETED_STATUSES, CaseStatus
from .util import now_iso, sha256_value, write_json


class BenchmarkRun(BaseModel):
    run_id: str
    suite_version: str
    model_identifier: str
    latencies_ms: list[float] = Field(default_factory=list)
    case_outcomes: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def true_median_latency(self) -> float | None:
        return statistics.median(self.latencies_ms) if self.latencies_ms else None

    def calculate_metrics(self) -> dict[str, Any]:
        completed = [
            case for case in self.case_outcomes
            if case.get("status") in {status.value for status in COMPLETED_STATUSES}
        ]
        scores = [float(case["score"]) for case in completed]
        return {
            "coverage": len(completed) / len(self.case_outcomes) if self.case_outcomes else 0.0,
            "macroScore": statistics.mean(scores) if scores else None,
            "completedCases": len(completed),
            "totalCases": len(self.case_outcomes),
            "medianLatencyMs": self.true_median_latency,
            "meanLatencyMs": statistics.mean(self.latencies_ms) if self.latencies_ms else None,
        }


def _distribution(values: list[float | int]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "standardDeviation": None, "q1": None, "q3": None, "minimum": None, "maximum": None}
    numeric = [float(value) for value in values]
    quartiles = statistics.quantiles(numeric, n=4, method="inclusive") if len(numeric) >= 2 else [numeric[0]] * 3
    return {
        "count": len(numeric),
        "mean": round(statistics.mean(numeric), 4),
        "median": round(statistics.median(numeric), 4),
        "standardDeviation": round(statistics.pstdev(numeric), 4),
        "q1": round(quartiles[0], 4),
        "q3": round(quartiles[2], 4),
        "minimum": round(min(numeric), 4),
        "maximum": round(max(numeric), 4),
    }


def _error_result(case: Any, status: CaseStatus, latency_ms: float | None, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "caseId": case.id,
        "dimension": case.dimension,
        "component": case.component,
        "title": case.title,
        "status": status.value,
        "score": None,
        "assertions": [],
        "latencyMs": latency_ms,
        "diagnostic": payload,
        "notes": case.notes,
    }


def run_provider(provider: Any) -> dict[str, Any]:
    started = now_iso()
    results: list[dict[str, Any]] = []
    terminal_error: ProviderError | None = None
    engine = AssertionEngine(provider if callable(getattr(provider, "embed", None)) else None)
    for case in cases():
        if terminal_error is not None:
            diagnostic = terminal_error.payload()
            diagnostic["skippedAfterTerminalProviderFailure"] = True
            results.append(_error_result(case, terminal_error.status, None, diagnostic))
            continue
        before = time.perf_counter()
        try:
            generation = provider.generate(case.prompt, image_data_url(case))
            latency_ms = round((time.perf_counter() - before) * 1000, 1)
            response_hash = sha256_value(generation.text)
            try:
                parsed = parse_json_response(generation.text)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                results.append(_error_result(
                    case,
                    CaseStatus.SCHEMA_VIOLATION,
                    latency_ms,
                    {
                        "category": CaseStatus.SCHEMA_VIOLATION.value,
                        "message": f"{type(exc).__name__}: {exc}",
                        "responseHash": response_hash,
                        "responsePreview": generation.text[:1000],
                    },
                ))
                continue

            assertion_results = engine.evaluate(parsed, case.assertions)
            serialized = [result.model_dump(mode="json") for result in assertion_results]
            schema_failed = any(result.mode == "structured_schema" and not result.passed for result in assertion_results)
            if schema_failed:
                status = CaseStatus.SCHEMA_VIOLATION
                score = None
            else:
                score = sum(result.passed for result in assertion_results) / len(assertion_results)
                status = CaseStatus.SUCCESS if score == 1.0 else CaseStatus.ASSERTION_FAILED
            results.append({
                "caseId": case.id,
                "dimension": case.dimension,
                "component": case.component,
                "title": case.title,
                "seed": case.seed,
                "status": status.value,
                "score": round(score, 4) if score is not None else None,
                "assertions": serialized,
                "latencyMs": latency_ms,
                "inputTokens": generation.input_tokens,
                "outputTokens": generation.output_tokens,
                "responseHash": response_hash,
                "response": parsed,
                "notes": case.notes,
            })
        except ProviderError as exc:
            latency_ms = round((time.perf_counter() - before) * 1000, 1)
            results.append(_error_result(case, exc.status, latency_ms, exc.payload()))
            if exc.status in {CaseStatus.AUTHENTICATION_ERROR, CaseStatus.BILLING_DEPLETED, CaseStatus.RATE_LIMITED}:
                terminal_error = exc
        except (TimeoutError, OSError) as exc:
            latency_ms = round((time.perf_counter() - before) * 1000, 1)
            results.append(_error_result(
                case,
                CaseStatus.TRANSPORT_TIMEOUT if isinstance(exc, TimeoutError) else CaseStatus.TRANSPORT_ERROR,
                latency_ms,
                {"category": "uncaught_transport", "message": f"{type(exc).__name__}: {exc}"},
            ))

    completed = [item for item in results if item["status"] in {status.value for status in COMPLETED_STATUSES}]
    scores = [item["score"] for item in completed]
    assertions = [assertion for item in completed for assertion in item["assertions"]]
    passed_assertions = sum(bool(assertion["passed"]) for assertion in assertions)
    latencies = [item["latencyMs"] for item in results if item.get("latencyMs") is not None]
    input_tokens = [item["inputTokens"] for item in results if item.get("inputTokens") is not None]
    output_tokens = [item["outputTokens"] for item in results if item.get("outputTokens") is not None]
    macro_score = statistics.mean(scores) if scores else None
    micro_rate = passed_assertions / len(assertions) if assertions else None
    status_counts = {status.value: sum(item["status"] == status.value for item in results) for status in CaseStatus}
    return {
        "provider": provider.name,
        "model": provider.model,
        "startedAt": started,
        "completedAt": now_iso(),
        "score": round(macro_score, 4) if macro_score is not None else None,
        "macroAverageCaseScore": round(macro_score, 4) if macro_score is not None else None,
        "macroScoreStandardDeviation": round(statistics.pstdev(scores), 4) if scores else None,
        "microAverageAssertionRate": round(micro_rate, 4) if micro_rate is not None else None,
        "coverage": round(len(completed) / len(results), 4) if results else 0.0,
        "completedCases": len(completed),
        "totalCases": len(results),
        "evaluatedAssertions": len(assertions),
        "passedAssertions": passed_assertions,
        "medianLatencyMs": statistics.median(latencies) if latencies else None,
        "meanLatencyMs": statistics.mean(latencies) if latencies else None,
        "metrics": {
            "latencyMs": _distribution(latencies),
            "inputTokens": _distribution(input_tokens),
            "outputTokens": _distribution(output_tokens),
        },
        "statusCounts": status_counts,
        "results": results,
    }


def run_all(providers: list[Any], runs_dir: Path) -> dict[str, Any]:
    manifest = suite_manifest()
    run = {
        "schemaVersion": 2,
        "runId": now_iso().replace(":", "").replace("-", ""),
        "createdAt": now_iso(),
        "suite": manifest,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "models": [run_provider(provider) for provider in providers],
    }
    run["sha256"] = sha256_value(run)
    destination = runs_dir / f"{run['runId']}.json"
    write_json(destination, run)
    write_json(runs_dir / "latest.json", run)
    return run


def load_latest(runs_dir: Path) -> dict[str, Any] | None:
    path = runs_dir / "latest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
