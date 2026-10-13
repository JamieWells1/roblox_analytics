"""Incremental day-level store so re-running the export never re-fetches a day
that is already on disk.

Roblox's analytics-query-api only serves a 28-day rolling window, so the only
way to see further back than that is to have asked while the day was still in
range and kept the answer. `history.json` is that keep: one value per
(metric, breakdown dimension, bucket, date), accumulated run over run and
never rewritten for a date it already has — except the most recent
`REFRESH_DAYS`, which are re-fetched every run because Roblox still revises
same-day and previous-day numbers (a same-day DailyRevenue is a partial, not a
final).
"""

import json
from datetime import date, timedelta

REFRESH_DAYS = 2  # today + yesterday are always re-fetched, everything older is final


def date_key(iso_timestamp):
    """'2026-09-06T00:00:00+00:00' -> '2026-09-06'."""
    return iso_timestamp[:10]


def load(path):
    if path.exists():
        return json.loads(path.read_text())
    return {"metrics": {}}


def save(path, history):
    path.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n")


def _series(history, metric, dim=None, bucket=None):
    m = history["metrics"].setdefault(metric, {"total": {}, "breakdowns": {}})
    if dim is None:
        return m["total"]
    return m["breakdowns"].setdefault(dim, {}).setdefault(bucket, {})


def existing_dates(history, metric):
    return set(history.get("metrics", {}).get(metric, {}).get("total", {}).keys())


def plan_fetch_start(history, metric, window_dates):
    """The earliest date that needs fetching for `metric`, or None if the whole
    requested window is already on disk and settled (nothing in the refresh
    tail to redo either)."""
    have = existing_dates(history, metric)
    missing = [d for d in window_dates if d not in have]
    refresh_tail = set(window_dates[-REFRESH_DAYS:])
    needed = sorted(set(missing) | (refresh_tail & set(window_dates)))
    return needed[0] if needed else None


def ingest_total(history, metric, result):
    """Merge a {"values": [{"breakdowns": [], "dataPoints": [...]}]} result into
    the metric's total series, keyed by date."""
    series = _series(history, metric)
    for value_block in result.get("values", []):
        if value_block.get("breakdowns"):
            continue  # this call asked for the total, not a breakdown bucket
        for point in value_block.get("dataPoints", []):
            series[date_key(point["time"])] = point["value"]


def ingest_breakdown(history, metric, dim, result):
    """Merge a breakdown result into history.metrics[metric].breakdowns[dim][bucket]."""
    for value_block in result.get("values", []):
        buckets = value_block.get("breakdowns", [])
        bucket = buckets[0] if buckets else "(unknown)"
        series = _series(history, metric, dim, bucket)
        for point in value_block.get("dataPoints", []):
            series[date_key(point["time"])] = point["value"]


def window_dates(days):
    """The `days` calendar dates ending today, oldest first — the natural
    request window for a daily-granularity export."""
    today = date.today()
    return [(today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]


def windowed_series(history, metric, dates, dim=None, bucket=None):
    series = _series(history, metric, dim, bucket) if dim else history.get("metrics", {}).get(metric, {}).get("total", {})
    return {d: series.get(d) for d in dates}
