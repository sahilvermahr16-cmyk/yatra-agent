"""One wrapper for every HTTP call the agent makes: timeout, retries, User-Agent and failure injection."""
import time

import httpx

import config

RETRY_WAITS = (0.5, 1.0)  # seconds to wait before the 2nd and the 3rd attempt
_injected: set[str] = set()


class ToolError(Exception):
    """A tool could not get an answer. The executor turns it into an ErrorRecord and a trace event.

    error_type: timeout | http_error | network_error | bad_response
    """

    def __init__(self, tool: str, error_type: str, message: str, attempts: int):
        super().__init__(f"{tool}: {error_type}: {message} (after {attempts} attempt(s))")
        self.tool = tool
        self.error_type = error_type
        self.message = message
        self.attempts = attempts


def inject_failures(tools: set[str]) -> None:
    """Make these tools time out on every attempt without touching the network (--inject-failure)."""
    _injected.clear()
    _injected.update(tools)


def _worth_retrying(status: int) -> bool:
    """Server trouble or rate limiting may pass; a bad request (4xx) will fail the same way again."""
    return status == 429 or status >= 500


def get_json(tool: str, url: str, params: dict | None = None, timeout: float | None = None,
             retries: int | None = None, retry_timeouts: bool = True,
             retry_wait: float | None = None) -> tuple[object, int]:
    """GET a JSON answer. Returns (json, attempts used). Raises ToolError when every attempt fails.
    retries: how many times to try again after the first attempt (default config.TOOL_RETRIES).
    retry_timeouts=False: a timeout ends the attempts at once (it has already cost the whole timeout).
    retry_wait: seconds to wait before each new attempt (default RETRY_WAITS)."""
    max_attempts = 1 + (config.TOOL_RETRIES if retries is None else retries)
    error_type, message = "network_error", "no attempt was made"
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            time.sleep(retry_wait if retry_wait is not None else RETRY_WAITS[min(attempt - 2, len(RETRY_WAITS) - 1)])
        try:
            if tool in _injected:
                raise httpx.TimeoutException("injected failure (--inject-failure): simulated timeout")
            resp = httpx.get(url, params=params, timeout=timeout or config.TOOL_TIMEOUT_SECONDS,
                             headers={"User-Agent": config.HTTP_USER_AGENT})
        except httpx.TimeoutException as err:  # checked first: a timeout is also an HTTPError
            error_type = "timeout"
            message = str(err) or f"no answer within {timeout or config.TOOL_TIMEOUT_SECONDS} s"
            if not retry_timeouts:
                raise ToolError(tool, error_type, message, attempt) from None
            continue
        except httpx.HTTPError as err:  # connection refused, DNS failure, ...
            error_type, message = "network_error", str(err) or type(err).__name__
            continue
        if resp.status_code != 200:
            error_type, message = "http_error", f"HTTP {resp.status_code}"
            if _worth_retrying(resp.status_code):
                continue
            raise ToolError(tool, error_type, message, attempt)
        try:
            return resp.json(), attempt
        except ValueError:
            raise ToolError(tool, "bad_response", "the answer was not valid JSON", attempt) from None
    raise ToolError(tool, error_type, message, max_attempts)
