"""Capability discovery: which metrics exist, and which dimensions each accepts.

Not documented machine-readably and drifts as Roblox ships metrics, so it is
probed once per universe and cached in that universe's capabilities.json;
--discover re-probes. An unknown metric/dimension errors with a distinctive
"was not found", which is what makes probing reliable.
"""

import json
from datetime import datetime, timedelta, timezone

from . import client

# Over-broad on purpose: a name that isn't real is rejected cleanly and costs
# one request, whereas a real metric left out of this list is invisible
# forever. Add speculative names here rather than trimming.
CANDIDATE_METRICS = [
    "DailyActiveUsers", "MonthlyActiveUsers", "WeeklyActiveUsers", "Visits",
    "NewUsers", "ReturningUsers", "UniqueVisits", "QualifiedPlays",
    "ForwardD1Retention", "ForwardD7Retention", "ForwardD14Retention", "ForwardD30Retention",
    "D1Retention", "D7Retention", "RetentionRate", "Churn",
    "SessionDurationSecondsAvg", "AverageSessionLength", "MedianSessionDuration",
    "PlaytimeHours", "PlaytimeMinutes", "TotalPlaytimeHours", "EngagementScore",
    "DailyRevenue", "Revenue", "RevenueByProduct", "DeveloperProductRevenue",
    "GamePassRevenue", "PayingUsers", "NewPayingUsers", "RepeatPayingUsers",
    "PayingUsersCVR", "PurchaseConversionRate", "AverageRevenuePerPayingUser",
    "AverageRevenuePerDailyActiveUser", "DailyRevenuePerPayingUser", "Purchases",
]

# No candidate here has ever come back supported for an acquisition/traffic
# channel (ads / home page / search / sponsored) — Roblox only exposes that
# split on the Creator Dashboard's own "Discovery" report, not through this
# API. Kept broad anyway so a future Roblox API addition gets picked up by
# --discover without anyone having to remember to add it.
CANDIDATE_DIMENSIONS = [
    "DeviceType", "OperatingSystem", "Country", "AgeGroup", "Gender",
    "Platform", "Locale", "Region", "AccountAge", "Product", "GamePass",
    "TrafficSource", "AcquisitionChannel", "ReferralSource", "EntryPoint",
]


def discover(universe, api_key, cache_path):
    """Probe every candidate metric, then every dimension on the ones that exist."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start = (now - timedelta(days=7)).isoformat().replace("+00:00", "Z")
    end = now.isoformat().replace("+00:00", "Z")

    metrics = {}
    print(f"probing {len(CANDIDATE_METRICS)} candidate metrics ...")
    for name in CANDIDATE_METRICS:
        verdict = client.classify(client.query(name, universe, api_key, start, end, "OneDay"))
        if verdict in ("supported", "unavailable"):
            metrics[name] = {"status": verdict, "dimensions": []}
        print(f"  {verdict:12} {name}", flush=True)

    print(f"\nprobing dimensions on {len(metrics)} metrics ...")
    for name, info in metrics.items():
        if info["status"] == "unavailable":
            continue  # can't tell dimensions apart from the metric's own outage
        for dim in CANDIDATE_DIMENSIONS:
            result = client.query(name, universe, api_key, start, end, "OneDay", breakdown=dim)
            if client.classify(result) == "supported":
                info["dimensions"].append(dim)
        print(f"  {name}: {', '.join(info['dimensions']) or 'none'}", flush=True)

    caps = {
        "probedAt": end,
        "universeId": universe,
        "metrics": metrics,
        "note": "Regenerate with --discover when Roblox ships new metrics.",
    }
    cache_path.write_text(json.dumps(caps, indent=2) + "\n")
    print(f"\nwrote {cache_path}")
    return caps


def load_capabilities(universe, api_key, cache_path, force=False):
    if not force and cache_path.exists():
        return json.loads(cache_path.read_text())
    print("no capability cache — discovering what the API supports (one-off, slow)\n")
    return discover(universe, api_key, cache_path)
