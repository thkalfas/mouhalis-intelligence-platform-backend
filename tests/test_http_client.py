"""Epic 1 support — shared Tier-1 HTTP client reliability contract."""
from __future__ import annotations

import pytest

from legal_intel.core.errors import PermanentError, TransientError
from legal_intel.platform.http import HttpClient, HttpResponse


class _ScriptedTransport:
    """Returns queued responses in order; records the calls it received."""

    def __init__(self, responses: list[HttpResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method, url, *, params=None, headers=None) -> HttpResponse:
        self.calls.append((method, url))
        return self._responses.pop(0)


def _resp(status: int, content: bytes = b"ok", ctype: str = "text/plain") -> HttpResponse:
    return HttpResponse(status_code=status, url="http://x", content=content,
                        headers={"content-type": ctype})


def _client(transport, sleeps):
    return HttpClient(transport, backoff=(1.0, 2.0, 3.0),
                      sleep=lambda s: sleeps.append(s))


def test_success_returns_response():
    t = _ScriptedTransport([_resp(200, b"hello")])
    sleeps: list[float] = []
    resp = _client(t, sleeps).get("http://x")
    assert resp.text == "hello"
    assert sleeps == []
    assert len(t.calls) == 1


def test_retries_then_succeeds_with_backoff():
    t = _ScriptedTransport([_resp(503), _resp(429), _resp(200, b"done")])
    sleeps: list[float] = []
    resp = _client(t, sleeps).get("http://x")
    assert resp.text == "done"
    assert sleeps == [1.0, 2.0]  # backed off before each retry
    assert len(t.calls) == 3


def test_exhausts_retries_raises_transient():
    t = _ScriptedTransport([_resp(503), _resp(503), _resp(503), _resp(503)])
    sleeps: list[float] = []
    with pytest.raises(TransientError):
        _client(t, sleeps).get("http://x")
    assert sleeps == [1.0, 2.0, 3.0]  # all backoffs consumed


def test_404_is_permanent_no_retry():
    t = _ScriptedTransport([_resp(404)])
    sleeps: list[float] = []
    with pytest.raises(PermanentError):
        _client(t, sleeps).get("http://x")
    assert sleeps == []
    assert len(t.calls) == 1


def test_accept_and_headers_merged():
    captured: dict = {}

    def transport(method, url, *, params=None, headers=None):
        captured["headers"] = headers
        captured["params"] = params
        return _resp(200)

    HttpClient(transport).get("http://x", accept="application/json",
                              params={"q": "1"}, headers={"X-Test": "y"})
    assert captured["headers"]["Accept"] == "application/json"
    assert captured["headers"]["Accept-Language"] == "el,en;q=0.9"
    assert captured["headers"]["X-Test"] == "y"
    assert captured["params"] == {"q": "1"}


def test_response_text_respects_charset():
    body = "Κείμενο".encode("utf-8")
    resp = HttpResponse(status_code=200, url="http://x", content=body,
                        headers={"content-type": "text/html; charset=utf-8"})
    assert resp.text == "Κείμενο"
