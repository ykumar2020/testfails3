import base64

from testfails.assertions import AssertionEngine
from testfails.benchmarks import (
    benchmark_image_data_url,
    cases,
    parse_json_response,
    suite_manifest,
)


class FixedEmbeddingBackend:
    def embed(self, texts):
        vectors = {
            "supportive response": [1.0, 0.0],
            "empathetic reference": [0.9, 0.1],
        }
        return [vectors[text] for text in texts]


def test_suite_has_fourteen_dimensions_and_seventy_versioned_probes():
    suite = suite_manifest()
    assert suite["dimensionCount"] == 14
    assert suite["caseCount"] == 70
    assert len({case.id for case in cases()}) == 70
    assert all(dimension["probeCount"] >= 5 for dimension in suite["dimensions"])
    assert len(suite["sha256"]) == 64
    assert all(len(case["promptHash"]) == 64 for case in suite["cases"])


def test_suite_hash_and_frozen_context_are_invariant():
    first = suite_manifest()
    second = suite_manifest()
    contextual = next(case for case in cases() if case.id == "context-01")
    assert first["sha256"] == second["sha256"]
    assert first["frozenEvaluationDate"] == "2026-10-13T00:00:00Z"
    assert "2026-10-13T00:00:00Z" in contextual.render_prompt()
    assert contextual.compute_prompt_hash() == next(item["promptHash"] for item in first["cases"] if item["id"] == "context-01")


def test_multimodal_suite_retains_sanity_png_and_adds_real_figures():
    header, encoded = benchmark_image_data_url().split(",", 1)
    multimodal = [case for case in cases() if case.dimension == "multimodal"]
    assert header == "data:image/png;base64"
    assert base64.b64decode(encoded).startswith(b"\x89PNG\r\n\x1a\n")
    assert multimodal[0].image_fixture == "builtin:color-block-8x4"
    assert {case.image_fixture for case in multimodal[1:]} == {
        "fixtures/multimodal/component-scores.png",
        "fixtures/multimodal/evidence-flow.png",
    }


def test_assertion_engine_supports_exact_lemma_schema_and_embeddings():
    engine = AssertionEngine(FixedEmbeddingBackend())
    results = engine.evaluate(
        {"label": "range", "response": "supportive response"},
        [
            {"id": "schema", "mode": "structured_schema", "schema": {"label": "str", "response": "str"}},
            {"id": "exact", "mode": "exact_match", "path": "label", "value": "range"},
            {"id": "semantic-term", "mode": "synonym_or_lemma", "path": "label", "groups": [["range", "interval"]]},
            {"id": "embedding", "mode": "embedding_similarity", "path": "response", "references": ["empathetic reference"], "threshold": 0.85},
        ],
    )
    assert [result.passed for result in results] == [True, True, True, True]
    assert results[-1].measured > 0.99


def test_education_and_multilingual_assertions_accept_calibrated_paraphrases():
    engine = AssertionEngine()
    education = next(case for case in cases() if case.id == "education-01")
    education_answer = {
        "precondition": "The collection must be ordered.",
        "invariant": "The target remains inside the candidate interval.",
        "complexity": "The worst case is logarithmic.",
    }
    multilingual = next(case for case in cases() if case.id == "multilingual-01")
    multilingual_answer = {"es": "La evidencia cuenta.", "fr": "Les preuves comptent."}
    assert all(result.passed for result in engine.evaluate(education_answer, education.assertions))
    assert all(result.passed for result in engine.evaluate(multilingual_answer, multilingual.assertions))


def test_response_parser_accepts_json_fence_without_weakening_schema_checks():
    parsed = parse_json_response('```json\n{"total": 37, "text": "Evidence matters"}\n```')
    assert parsed["total"] == 37
