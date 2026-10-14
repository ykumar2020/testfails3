"""Typed, extensible assertion engine for testFAILS3 benchmark probes."""
from __future__ import annotations

import math
import re
import unicodedata
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError, create_model


class EmbeddingBackend(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class AssertionResult(BaseModel):
    assertion_id: str
    passed: bool
    mode: str
    details: str | None = None
    measured: float | int | str | None = None


def _at(document: dict[str, Any], path: str) -> Any:
    value: Any = document
    for part in path.split(".") if path else []:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value).casefold())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


@lru_cache(maxsize=8)
def _spacy_pipeline(language: str):
    try:
        import spacy

        installed = list(spacy.util.get_installed_models())
        matching = next((name for name in installed if name.startswith(language + "_")), None)
        return spacy.load(matching, disable=["parser", "ner"]) if matching else spacy.blank(language)
    except (ImportError, OSError):
        return None


def _lemmas(text: Any, language: str = "en") -> set[str]:
    folded = _fold(text)
    pipeline = _spacy_pipeline(language)
    if pipeline is not None:
        tokens = {
            _fold(token.lemma_ or token.text)
            for token in pipeline(folded)
            if not token.is_space and not token.is_punct
        }
    else:
        tokens = set(re.findall(r"[\w+-]+", folded))
    # Conservative suffix variants keep evaluation usable when a language model
    # package is unavailable; details disclose that the fallback was used.
    expanded = set(tokens)
    for token in tokens:
        if len(token) > 4 and token.endswith(("es", "s")):
            expanded.add(token[:-2] if token.endswith("es") else token[:-1])
        if len(token) > 5 and token.endswith("ing"):
            expanded.add(token[:-3])
    return expanded


class BaseAssertion(ABC):
    mode: str

    def __init__(self, spec: dict[str, Any]):
        self.spec = spec
        self.assertion_id = str(spec.get("id") or spec.get("mode") or "assertion")

    def result(self, passed: bool, details: str, measured: Any = None) -> AssertionResult:
        return AssertionResult(
            assertion_id=self.assertion_id,
            passed=passed,
            mode=self.mode,
            details=details,
            measured=measured if isinstance(measured, (float, int, str)) else None,
        )

    @abstractmethod
    def evaluate(self, document: dict[str, Any], backend: EmbeddingBackend | None) -> AssertionResult:
        raise NotImplementedError


class ExactMatchAssertion(BaseAssertion):
    mode = "exact_match"

    def evaluate(self, document: dict[str, Any], backend: EmbeddingBackend | None) -> AssertionResult:
        actual = _at(document, self.spec.get("path", ""))
        expected = self.spec.get("value")
        return self.result(actual == expected, f"expected exact value at {self.spec.get('path') or '<root>'}")


class SynonymOrLemmaAssertion(BaseAssertion):
    mode = "synonym_or_lemma"

    def evaluate(self, document: dict[str, Any], backend: EmbeddingBackend | None) -> AssertionResult:
        actual = _at(document, self.spec.get("path", ""))
        language = str(self.spec.get("language", "en"))
        actual_text = _fold(actual)
        actual_lemmas = _lemmas(actual, language)
        groups = self.spec.get("groups") or []

        def group_matches(group: list[Any]) -> bool:
            for candidate in group:
                candidate_text = _fold(candidate)
                if candidate_text in actual_text or (_lemmas(candidate, language) & actual_lemmas):
                    return True
            return False

        outcomes = [group_matches(group) for group in groups]
        match = self.spec.get("match", "all")
        passed = all(outcomes) if match == "all" else any(outcomes)
        backend_name = "spaCy" if _spacy_pipeline(language) is not None else "rule-based lemma fallback"
        return self.result(passed, f"{match} of {len(groups)} synonym/lemma groups via {backend_name}")


TYPE_MAP: dict[str, Any] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "object": dict[str, Any],
    "array": list[Any],
    "array_str": list[str],
    "array_int": list[int],
}


class StructuredSchemaAssertion(BaseAssertion):
    mode = "structured_schema"

    def evaluate(self, document: dict[str, Any], backend: EmbeddingBackend | None) -> AssertionResult:
        fields: dict[str, tuple[Any, Any]] = {}
        for name, type_name in (self.spec.get("schema") or {}).items():
            required = True
            if isinstance(type_name, dict):
                required = bool(type_name.get("required", True))
                type_name = type_name.get("type", "str")
            annotation = TYPE_MAP.get(str(type_name))
            if annotation is None:
                return self.result(False, f"unsupported schema type {type_name!r}")
            fields[name] = (annotation, ... if required else None)
        model = create_model(
            f"ProbeSchema_{re.sub(r'[^A-Za-z0-9_]', '_', self.assertion_id)}",
            __config__=ConfigDict(extra="forbid", strict=True),
            **fields,
        )
        try:
            model.model_validate(document)
            return self.result(True, f"Pydantic schema accepted {len(fields)} fields")
        except ValidationError as exc:
            first = exc.errors(include_url=False)[0]
            return self.result(False, f"Pydantic schema violation at {first.get('loc')}: {first.get('msg')}")


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("embedding vectors must have equal non-zero length")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


class EmbeddingSimilarityAssertion(BaseAssertion):
    mode = "embedding_similarity"

    def evaluate(self, document: dict[str, Any], backend: EmbeddingBackend | None) -> AssertionResult:
        if backend is None:
            return self.result(False, "embedding backend unavailable")
        actual = str(_at(document, self.spec.get("path", "")))
        references = [str(item) for item in self.spec.get("references", [])]
        threshold = float(self.spec.get("threshold", 0.85))
        vectors = backend.embed([actual, *references])
        similarity = max((_cosine(vectors[0], vector) for vector in vectors[1:]), default=0.0)
        return self.result(
            similarity >= threshold,
            f"maximum cosine similarity {similarity:.4f}; threshold {threshold:.4f}",
            round(similarity, 6),
        )


class RuleAssertion(BaseAssertion):
    """Deterministic structural rules retained for bounded benchmark checks."""

    mode = "rule"

    def evaluate(self, document: dict[str, Any], backend: EmbeddingBackend | None) -> AssertionResult:
        kind = str(self.spec["mode"])
        actual = _at(document, self.spec.get("path", ""))
        text = str(actual)
        folded = text.casefold()
        values = self.spec.get("values", [])
        if kind == "contains_all":
            passed = all(str(value).casefold() in folded for value in values)
        elif kind == "contains_any":
            passed = any(str(value).casefold() in folded for value in values)
        elif kind == "excludes_any":
            passed = all(str(value).casefold() not in folded for value in values)
        elif kind == "word_count":
            count = len(text.split())
            passed = self.spec.get("minimum", 0) <= count <= self.spec.get("maximum", float("inf"))
            return self.result(passed, f"word count {count}", count)
        elif kind == "regex_count":
            count = len(re.findall(str(self.spec.get("value")), text))
            passed = self.spec.get("minimum", 0) <= count <= self.spec.get("maximum", float("inf"))
            return self.result(passed, f"regex count {count}", count)
        elif kind == "tool_sequence":
            passed = [item.get("tool") for item in actual] == self.spec.get("value")
        elif kind == "excludes_tool":
            passed = all(item.get("tool") != self.spec.get("value") for item in actual)
        elif kind == "all_args_contain":
            passed = all(
                all(item.get("args", {}).get(key) == value for key, value in self.spec.get("value", {}).items())
                for item in actual
            )
        else:
            return self.result(False, f"unknown rule mode {kind}")
        return self.result(passed, f"{kind} at {self.spec.get('path') or '<root>'}")


class AssertionEngine:
    MODES: ClassVar[dict[str, type[BaseAssertion]]] = {
        "exact_match": ExactMatchAssertion,
        "synonym_or_lemma": SynonymOrLemmaAssertion,
        "structured_schema": StructuredSchemaAssertion,
        "embedding_similarity": EmbeddingSimilarityAssertion,
    }

    def __init__(self, embedding_backend: EmbeddingBackend | None = None):
        self.embedding_backend = embedding_backend

    def evaluate(self, document: dict[str, Any], specs: list[dict[str, Any]]) -> list[AssertionResult]:
        results: list[AssertionResult] = []
        for spec in specs:
            assertion_type = self.MODES.get(str(spec.get("mode")), RuleAssertion)
            try:
                results.append(assertion_type(spec).evaluate(document, self.embedding_backend))
            except (KeyError, TypeError, ValueError) as exc:
                results.append(
                    AssertionResult(
                        assertion_id=str(spec.get("id") or spec.get("mode") or "assertion"),
                        passed=False,
                        mode=str(spec.get("mode") or "unknown"),
                        details=f"{type(exc).__name__}: {exc}",
                    )
                )
        return results

