import io
import urllib.error

import pytest

from testfails import providers
from testfails.status import CaseStatus


@pytest.mark.parametrize(
    ("http_code", "expected"),
    [
        (401, CaseStatus.AUTHENTICATION_ERROR),
        (402, CaseStatus.BILLING_DEPLETED),
        (429, CaseStatus.RATE_LIMITED),
        (504, CaseStatus.TRANSPORT_TIMEOUT),
    ],
)
def test_http_failures_are_categorized(monkeypatch, http_code, expected):
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("https://example.test", http_code, "failure", {}, io.BytesIO(b'{"error":"classified"}'))

    monkeypatch.setattr(providers.urllib.request, "urlopen", fail)
    with pytest.raises(providers.ProviderError) as caught:
        providers._json_request("https://example.test", {}, {})
    assert caught.value.status is expected
    assert caught.value.http_status == http_code
    assert caught.value.payload()["category"] == expected.value


def test_socket_timeout_is_categorized(monkeypatch):
    monkeypatch.setattr(providers.urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(providers.ProviderError) as caught:
        providers._json_request("https://example.test", {}, {}, timeout=3)
    assert caught.value.status is CaseStatus.TRANSPORT_TIMEOUT

