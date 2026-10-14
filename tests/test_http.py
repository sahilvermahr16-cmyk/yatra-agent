"""The HTTP wrapper: retries, no retry on a bad request, failure injection. No network: httpx.get is faked."""
import httpx
import pytest

from tools import http
from tools.http import ToolError, get_json, inject_failures


class FakeResponse:
    def __init__(self, status=200, payload=None, bad_json=False):
        self.status_code, self.payload, self.bad_json = status, payload, bad_json

    def json(self):
        if self.bad_json:
            raise ValueError("not json")
        return self.payload


@pytest.fixture
def fake_get(monkeypatch):
    """Queue answers (FakeResponse or exception) for httpx.get; records how often it was called."""
    calls = []

    def install(*answers):
        queue = list(answers)

        def fake(url, params=None, timeout=None, headers=None):
            calls.append(headers)
            answer = queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        monkeypatch.setattr(http.httpx, "get", fake)
        monkeypatch.setattr(http.time, "sleep", lambda s: None)
        return calls

    yield install
    inject_failures(set())


def test_success_on_first_attempt_sends_user_agent(fake_get):
    calls = fake_get(FakeResponse(payload={"ok": 1}))
    assert get_json("geocode", "https://x") == ({"ok": 1}, 1)
    assert "yatra-agent" in calls[0]["User-Agent"]


def test_timeout_is_retried_then_succeeds(fake_get):
    calls = fake_get(httpx.TimeoutException("slow"), FakeResponse(payload={"ok": 1}))
    assert get_json("geocode", "https://x") == ({"ok": 1}, 2)
    assert len(calls) == 2


def test_server_error_is_retried(fake_get):
    fake_get(FakeResponse(status=503), FakeResponse(payload=[]))
    assert get_json("geocode", "https://x") == ([], 2)


def test_gives_up_after_all_retries(fake_get):
    calls = fake_get(*[httpx.TimeoutException("slow")] * 3)
    with pytest.raises(ToolError) as err:
        get_json("geocode", "https://x")
    assert (err.value.error_type, err.value.attempts, len(calls)) == ("timeout", 3, 3)


def test_bad_request_is_not_retried(fake_get):
    calls = fake_get(FakeResponse(status=404))
    with pytest.raises(ToolError) as err:
        get_json("geocode", "https://x")
    assert (err.value.error_type, err.value.message, len(calls)) == ("http_error", "HTTP 404", 1)


def test_network_error_is_reported(fake_get):
    fake_get(*[httpx.ConnectError("refused")] * 3)
    with pytest.raises(ToolError) as err:
        get_json("geocode", "https://x")
    assert err.value.error_type == "network_error"


def test_invalid_json_is_a_bad_response(fake_get):
    fake_get(FakeResponse(bad_json=True))
    with pytest.raises(ToolError) as err:
        get_json("geocode", "https://x")
    assert err.value.error_type == "bad_response"


def test_injected_failure_times_out_without_network(fake_get):
    calls = fake_get()  # any real call would fail: the queue is empty
    inject_failures({"weather"})
    with pytest.raises(ToolError) as err:
        get_json("weather", "https://x")
    assert (err.value.error_type, err.value.attempts, len(calls)) == ("timeout", 3, 0)
    assert "injected" in err.value.message


def test_a_timeout_can_end_the_attempts_at_once(fake_get):
    calls = fake_get(httpx.ReadTimeout("slow"), FakeResponse(payload={"ok": 1}))
    with pytest.raises(ToolError) as err:
        get_json("osm", "https://x", retries=1, retry_timeouts=False)
    assert err.value.error_type == "timeout" and err.value.attempts == 1 and len(calls) == 1


def test_a_quick_refusal_is_asked_again_after_the_given_wait(fake_get, monkeypatch):
    waits = []
    fake_get(FakeResponse(status=504), FakeResponse(payload={"ok": 1}))
    monkeypatch.setattr(http.time, "sleep", waits.append)
    assert get_json("osm", "https://x", retries=1, retry_timeouts=False, retry_wait=3) == ({"ok": 1}, 2)
    assert waits == [3]
