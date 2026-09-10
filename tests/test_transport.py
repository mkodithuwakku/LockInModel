import requests
import pytest
from transport import CachedHTTP, DataUnavailable


class Response:
    def __init__(self, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError()

    def json(self):
        return {"rows": [1]}


class Session:
    def __init__(self, result):
        self.calls = 0
        self.result = result

    def get(self, *args, **kwargs):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_cache_only_and_reuse(tmp_path):
    session = Session(Response())
    client = CachedHTTP(tmp_path, session, clock=lambda: 100, sleeper=lambda _: None)
    with pytest.raises(DataUnavailable):
        client.get("https://example.test/data", offline=True)
    assert session.calls == 0
    first = client.get("https://example.test/data")
    assert client.get("https://example.test/data", offline=True) == first
    assert session.calls == 1


@pytest.mark.parametrize(
    "response", [Response(429, {"Retry-After": "1800"}), requests.ReadTimeout()]
)
def test_failure_opens_persistent_circuit(tmp_path, response):
    session = Session(response)
    client = CachedHTTP(tmp_path, session, clock=lambda: 100, sleeper=lambda _: None)
    with pytest.raises(DataUnavailable):
        client.get("https://example.test/a")
    other = CachedHTTP(tmp_path, session, clock=lambda: 101, sleeper=lambda _: None)
    with pytest.raises(DataUnavailable):
        other.get("https://example.test/b")
    assert session.calls == 1
