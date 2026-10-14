import statistics

import testfails.runner as runner_module
from testfails.benchmarks import TestCase
from testfails.providers import Generation, ProviderError
from testfails.runner import _distribution, run_all, run_provider
from testfails.status import CaseStatus


class SchemaViolatingProvider:
    name = "schema-test-double"
    model = "test-only"

    def generate(self, prompt, image_data_url=None):
        return Generation(text="{}", model=self.model, input_tokens=2, output_tokens=2, raw_usage={})


class BillingProvider:
    name = "billing-test-double"
    model = "test-only"

    def __init__(self):
        self.calls = 0

    def generate(self, prompt, image_data_url=None):
        self.calls += 1
        raise ProviderError("HTTP 402: prepaid credits depleted", status=CaseStatus.BILLING_DEPLETED, http_status=402)


def test_runner_records_all_probes_and_hashes_run(tmp_path):
    run = run_all([SchemaViolatingProvider()], tmp_path)
    model = run["models"][0]
    assert model["totalCases"] == 70
    assert model["completedCases"] == 0
    assert model["coverage"] == 0.0
    assert model["statusCounts"]["schema_violation"] == 70
    assert len(run["sha256"]) == 64
    assert (tmp_path / "latest.json").exists()


def test_billing_failure_is_classified_and_short_circuits_paid_calls():
    provider = BillingProvider()
    model = run_provider(provider)
    assert provider.calls == 1
    assert model["totalCases"] == 70
    assert model["coverage"] == 0.0
    assert model["score"] is None
    assert model["statusCounts"]["billing_depleted"] == 70
    assert model["results"][0]["diagnostic"]["httpStatus"] == 402
    assert model["results"][1]["diagnostic"]["skippedAfterTerminalProviderFailure"] is True


def test_even_sample_median_and_standard_statistics_are_mathematically_standard():
    latencies = [800.0, 850.0, 875.0, 890.0, 895.0, 899.4, 900.0, 909.4, 915.0, 930.0, 945.0, 960.0, 980.0, 1000.0]
    summary = _distribution(latencies)
    assert summary["median"] == 904.7
    assert summary["mean"] == round(statistics.mean(latencies), 4)
    assert summary["standardDeviation"] == round(statistics.pstdev(latencies), 4)
    assert summary["q1"] is not None and summary["q3"] is not None


def test_macro_and_micro_scores_remain_separate(monkeypatch):
    probes = [
        TestCase(
            case_id=f"metric-{index:02d}",
            dimension="metric",
            component="Metric test",
            title="Aggregation",
            prompt_template=prompt,
            seed=index,
            expected_assertions=[
                {"id": "schema", "mode": "structured_schema", "schema": {"value": "int"}},
                {"id": "value", "mode": "exact_match", "path": "value", "value": expected},
            ],
        )
        for index, (prompt, expected) in enumerate((("first", 1), ("second", 3)), start=1)
    ]

    class MixedProvider:
        name = "mixed"
        model = "test-only"

        def generate(self, prompt, image_data_url=None):
            value = 1 if prompt == "first" else 2
            return Generation(text=f'{{"value": {value}}}', model=self.model, input_tokens=10, output_tokens=2, raw_usage={})

    monkeypatch.setattr(runner_module, "cases", lambda: probes)
    model = run_provider(MixedProvider())
    assert model["coverage"] == 1.0
    assert model["macroAverageCaseScore"] == 0.75
    assert model["microAverageAssertionRate"] == 0.75
    assert model["macroScoreStandardDeviation"] == 0.25
