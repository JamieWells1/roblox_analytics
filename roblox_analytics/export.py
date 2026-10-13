"""Pull Roblox Open Cloud analytics for one game into its history + a snapshot.

Writes, next to the game's config.json:
  history.json   every day ever fetched, kept forever (until it rolls off
                  Roblox's own 28-day window before it's ever fetched)
  export.json    a snapshot of the requested window, read back out of
                  history.json — what the dashboard actually reads
  capabilities.json  per-universe metric/dimension support cache

Re-running this only fetches days missing from history.json (plus the last
`history.REFRESH_DAYS`, which Roblox still revises) — a daily cron-style run
costs one day of API calls, not the whole window, every time.

The custom events and funnels a game logs itself (onboarding/loop funnels,
custom events) have no read endpoint on this API — dashboard-only, recorded
below in NOT_AVAILABLE. Likewise, Roblox does not expose an acquisition /
traffic-source breakdown (ads vs. home page vs. search vs. sponsored) through
this API — that split only exists on the Creator Dashboard's own Discovery
report, not as a queryable dimension. Don't build around data this call can't
return.
"""

import argparse
import json
import pathlib
from datetime import datetime, timedelta, timezone

from . import client, config as config_mod, env, history as history_mod
from .capabilities import load_capabilities, CANDIDATE_DIMENSIONS

DEFAULT_LOOKBACK_DAYS = 28  # several metrics only retain 28 days; the API rejects a longer window
DEFAULT_BREAKDOWN = "Platform"  # the one breakdown that changes what gets built (mobile vs. desktop UI/pacing)

NOT_AVAILABLE = {
    "customEventsAndFunnels": (
        "Onboarding/repeatable funnels and custom events logged in-game have NO "
        "read API — FunnelStepCompletion, FunnelConversion, OnboardingFunnel and "
        "CustomEvents are all rejected as nonexistent metrics. Visible ONLY on "
        "the Creator Dashboard's Analytics tab. Do not infer them from this file."
    ),
    "perProductRevenue": (
        "Revenue cannot be split by product. RevenueByProduct/DeveloperProductRevenue/"
        "GamePassRevenue are not metrics, and DailyRevenue rejects a Product or GamePass "
        "breakdown. DailyRevenue is one undifferentiated number. Which SKUs sell is "
        "Dashboard-only; `context.monetisation` below lists what COULD have sold, not "
        "what did."
    ),
    "acquisitionSource": (
        "Where players come from (ads, home page / recommendations, search, "
        "sponsored, direct link) is NOT exposed by this API under any probed "
        "dimension name. It exists only on the Creator Dashboard's Discovery "
        "report. If Roblox ever ships it as a queryable dimension, --discover "
        "will pick it up automatically (see capabilities.py's candidate list)."
    ),
}


def build_arg_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--universe", help="universe id, not place id (default: config.json's)")
    parser.add_argument("--days", type=int, default=DEFAULT_LOOKBACK_DAYS,
                        help=f"snapshot window for export.json (default {DEFAULT_LOOKBACK_DAYS})")
    parser.add_argument("--granularity", default="OneDay",
                        choices=("OneHour", "OneDay", "OneWeek", "OneMonth"))
    parser.add_argument("--metrics", help="comma-separated subset (default: every supported metric)")
    parser.add_argument("--breakdowns", default="default",
                        help="'default' (Platform), 'all', 'none', or a comma-separated list of dimensions")
    parser.add_argument("--discover", action="store_true", help="re-probe API capabilities, then export")
    parser.add_argument("--env-file", help="read the key from this file instead of config.json's")
    return parser


def main(config_dir, argv=None):
    config_dir = pathlib.Path(config_dir)
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    cfg = config_mod.GameConfig(config_dir, config_dir / "config.json")
    api_key, key_source = env.find_api_key(cfg.root, args.env_file or cfg.env_file)
    universe = args.universe or cfg.require_universe_id()

    caps_path = config_dir / "capabilities.json"
    caps = load_capabilities(universe, api_key, caps_path, force=args.discover)

    metrics = args.metrics.split(",") if args.metrics else list(caps["metrics"])
    wanted_dates = history_mod.window_dates(args.days)

    history = history_mod.load(config_dir / "history.json")
    history["universeId"] = universe

    now = datetime.now(timezone.utc).replace(microsecond=0)
    now_iso = now.isoformat().replace("+00:00", "Z")

    print(f"\n{cfg.name}: universe {universe}, key from {key_source}")
    print(f"{args.days}d snapshot at {args.granularity}, {len(metrics)} metrics, breakdowns={args.breakdowns}\n")

    fetched, skipped_cached, skipped_unsupported, errored = 0, 0, 0, 0
    recheck = False

    for metric in metrics:
        info = caps["metrics"].get(metric, {"status": "unknown", "dimensions": []})
        if info["status"] == "unavailable":
            probe = client.query(metric, universe, api_key, wanted_dates[0], now_iso, args.granularity)
            if client.classify(probe) == "supported":
                info = {"status": "supported", "dimensions": [
                    d for d in CANDIDATE_DIMENSIONS
                    if client.classify(client.query(metric, universe, api_key, wanted_dates[0], now_iso,
                                                      args.granularity, breakdown=d)) == "supported"
                ]}
                caps["metrics"][metric] = info
                recheck = True
                print(f"  {metric}: now available — capability cache updated")
        if info["status"] != "supported":
            skipped_unsupported += 1
            continue

        fetch_from = history_mod.plan_fetch_start(history, metric, wanted_dates)
        if fetch_from is None:
            skipped_cached += 1
            print(f"  {metric}: cached, nothing new to fetch")
            continue

        if args.breakdowns == "none":
            dims = []
        elif args.breakdowns == "all":
            dims = info["dimensions"]
        elif args.breakdowns == "default":
            dims = [DEFAULT_BREAKDOWN] if DEFAULT_BREAKDOWN in info["dimensions"] else []
        else:
            dims = [d for d in args.breakdowns.split(",") if d in info["dimensions"]]

        start_iso = f"{fetch_from}T00:00:00Z"
        result = client.query(metric, universe, api_key, start_iso, now_iso, args.granularity)
        if "error" in result:
            errored += 1
            print(f"  ! {metric}: {str(result.get('detail', result['error']))[:160]}", flush=True)
            continue
        history_mod.ingest_total(history, metric, result)
        dim_errors = []
        for dim in dims:
            dim_result = client.query(metric, universe, api_key, start_iso, now_iso, args.granularity, breakdown=dim)
            if "error" in dim_result:
                dim_errors.append(dim)
                continue
            history_mod.ingest_breakdown(history, metric, dim, dim_result)
        fetched += 1
        ok_dims = [d for d in dims if d not in dim_errors]
        print(f"  {metric}: fetched from {fetch_from}{''.join(' +' + d for d in ok_dims)}"
              f"{' (breakdown failed: ' + ', '.join(dim_errors) + ')' if dim_errors else ''}", flush=True)

    if recheck:
        caps_path.write_text(json.dumps(caps, indent=2) + "\n")

    history["lastFetched"] = now_iso
    history_mod.save(config_dir / "history.json", history)

    export = {
        "generatedAt": now_iso,
        "universeId": universe,
        "window": {"startTime": f"{wanted_dates[0]}T00:00:00Z", "endTime": now_iso, "granularity": args.granularity},
        "notAvailable": NOT_AVAILABLE,
        "context": {"monetisation": config_mod.monetisation_context(cfg)},
        "metrics": {},
    }
    for metric in metrics:
        info = caps["metrics"].get(metric, {"status": "unknown", "dimensions": []})
        if info["status"] != "supported":
            export["metrics"][metric] = {"status": info["status"]}
            continue
        entry = {
            "status": "supported",
            "total": history_mod.windowed_series(history, metric, wanted_dates),
        }
        breakdowns = history.get("metrics", {}).get(metric, {}).get("breakdowns", {})
        if breakdowns:
            entry["breakdowns"] = {
                dim: {bucket: history_mod.windowed_series(history, metric, wanted_dates, dim, bucket)
                      for bucket in buckets}
                for dim, buckets in breakdowns.items()
            }
        export["metrics"][metric] = entry

    (config_dir / "export.json").write_text(json.dumps(export, indent=2) + "\n")

    print(f"\n{fetched} metric(s) fetched, {skipped_cached} already up to date, "
          f"{skipped_unsupported} unsupported on this universe, {errored} errored (will retry next run)")
    print(f"wrote {config_dir / 'history.json'} and {config_dir / 'export.json'}")
    return 0
