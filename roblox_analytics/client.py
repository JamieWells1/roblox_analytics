"""Thin client for the Roblox Open Cloud analytics-query-api.

https://create.roblox.com/docs/cloud/guides/analytics

Every query is a long-running operation: the POST returns 202 with an operation
path, which is polled until `done`. An idle universe answers 200 inline instead.
The API rate-limits hard (429) after a few dozen queries, so requests are paced
and retried with backoff.
"""

import json
import time
import urllib.error
import urllib.request

BASE = "https://apis.roblox.com"
ENDPOINT = "/analytics-query-api/v1/universes/{u}/metrics"

POLL_INTERVAL_SECONDS = 2
POLL_MAX_ATTEMPTS = 30

REQUEST_GAP_SECONDS = 1.5
RATE_LIMIT_BACKOFF = (20, 60, 120)

_last_request = [0.0]


def call(method, path, api_key, payload=None):
    """One Open Cloud request, paced and retried through rate limits.

    Returns (status, decoded body).
    """
    body = json.dumps(payload).encode() if payload is not None else None
    for attempt in range(len(RATE_LIMIT_BACKOFF) + 1):
        gap = REQUEST_GAP_SECONDS - (time.monotonic() - _last_request[0])
        if gap > 0:
            time.sleep(gap)
        req = urllib.request.Request(
            BASE + path, data=body, method=method,
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                _last_request[0] = time.monotonic()
                return resp.status, json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as err:
            _last_request[0] = time.monotonic()
            detail = err.read().decode()[:500]
            if err.code == 429 and attempt < len(RATE_LIMIT_BACKOFF):
                wait = RATE_LIMIT_BACKOFF[attempt]
                print(f"    rate-limited, waiting {wait}s ...", flush=True)
                time.sleep(wait)
                continue
            return err.code, {"detail": detail}
        except urllib.error.URLError as err:
            _last_request[0] = time.monotonic()
            return 0, {"detail": str(err.reason)}
    return 429, {"detail": "rate-limited past the backoff ladder"}


def unwrap(body):
    """Flatten an operation envelope to its result, or a normalised error."""
    if body.get("error"):
        err = body["error"]
        return {"error": err.get("code", "error"), "detail": err.get("message", str(err))}
    return body.get("response", body)


def poll(op_path, api_key):
    op_path = op_path.lstrip("/")
    if not op_path.startswith("analytics-query-api/"):
        op_path = f"analytics-query-api/{op_path}"
    for _ in range(POLL_MAX_ATTEMPTS):
        status, body = call("GET", "/" + op_path, api_key)
        if status != 200:
            return {"error": status, "detail": body.get("detail", "")}
        if body.get("done"):
            return unwrap(body)
        time.sleep(POLL_INTERVAL_SECONDS)
    waited = POLL_MAX_ATTEMPTS * POLL_INTERVAL_SECONDS
    return {"error": "timeout", "detail": f"operation not done after {waited}s"}


def query(metric, universe, api_key, start, end, granularity, breakdown=None):
    payload = {
        "metric": metric,
        "granularity": granularity,
        "startTime": start,
        "endTime": end,
    }
    if breakdown:
        payload["breakdown"] = [breakdown]
    status, body = call("POST", ENDPOINT.format(u=universe), api_key, payload)
    if status == 200:
        return unwrap(body)
    if status == 202:
        op_path = body.get("path")
        if not op_path:
            return {"error": 202, "detail": json.dumps(body)[:500]}
        return poll(op_path, api_key)
    detail = body.get("detail", "")
    try:  # the error envelope arrives as the HTTP body on a 400
        detail = json.loads(detail).get("error", {}).get("message", detail)
    except (ValueError, AttributeError):
        pass
    return {"error": status, "detail": detail}


def classify(result):
    """What a probe result says about EXISTENCE, as opposed to about the game."""
    if "error" not in result:
        return "supported"
    detail = str(result.get("detail", ""))
    if "was not found" in detail or "is not supported" in detail:
        return "unsupported"
    if "not available for Universe" in detail:
        return "unavailable"  # real, but this universe can't serve it yet
    return "error"
