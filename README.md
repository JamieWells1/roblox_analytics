# roblox_analytics

Reusable Roblox Open Cloud analytics export + dashboard, shared across games
rather than copy-pasted into each one. Used by `build_a_galaxy` and
`escape_a_black_hole` as a git submodule at `vendor/roblox_analytics`.

Pulls DAU/MAU, retention, revenue, paying users, CVR, ARPPU, session length
and playtime for a universe, keeps an ever-growing day-by-day history on disk
(Roblox's own API only serves a 28-day rolling window), and serves an
interactive Grafana-style dashboard over it with a universe switcher.

## Wiring a game up

1. Add this repo as a submodule:
   ```
   git submodule add https://github.com/JamieWells1/roblox_analytics.git vendor/roblox_analytics
   ```
2. Create `scripts/analytics/config.json`:
   ```json
   {
     "game": "Build a Galaxy",
     "universeId": "10600160409",
     "catalogueFile": "../monetisation/catalogue.json",
     "idsFile": "../monetisation/ids.json"
   }
   ```
   `catalogueFile`/`idsFile` are optional — only needed if the game runs the
   monetisation sync, so revenue numbers can be read against real prices.
   `envFile` is optional too; defaults to `.env.local`/`.env` at the repo root.
3. Create a one-line shim at `scripts/analytics/export.py`:
   ```python
   #!/usr/bin/env python3
   import pathlib, sys
   HERE = pathlib.Path(__file__).resolve().parent
   sys.path.insert(0, str(HERE.parents[1] / "vendor"))
   from roblox_analytics.export import main
   if __name__ == "__main__":
       raise SystemExit(main(HERE))
   ```
4. Run it: `python3 scripts/analytics/export.py`. The Open Cloud key comes
   from `ROBLOX_OPEN_CLOUD_KEY` / `ROBLOX_API_KEY` in the environment or
   `.env.local`, and needs the `universe-analytics:read` scope.

Commit `scripts/analytics/history.json`, `export.json` and
`capabilities.json` — that's what makes the "only fetch new days" logic work
across machines and over time, and what the dashboard reads.

## Running the dashboard

```
python3 vendor/roblox_analytics/dashboard/serve.py
```

Auto-discovers every sibling game directory with a `scripts/analytics/config.json`
and lets you switch between them from the page — no manual wiring beyond step
1-3 above. Open http://localhost:8800.

## What this can and can't show you

Can: DAU/MAU, stickiness, D1/D7/D30 retention, total revenue, revenue per
active user (ARPDAU — spend independent of headcount), revenue per paying
user (ARPPU), % of players who pay, session length, playtime, and a platform
(device-type-ish) breakdown of the above where Roblox supports one.

Can't, because the API itself doesn't expose it (see `notAvailable` in
`export.json`, surfaced in the dashboard too):
- **Acquisition / traffic source** (ads, home page recommendations, search,
  sponsored). This only exists on the Creator Dashboard's own Discovery
  report, not as a queryable metric or dimension.
- **Per-product revenue.** `DailyRevenue` is one undifferentiated number;
  which SKU sold is Dashboard-only.
- **Custom events and funnels** a game logs itself (onboarding/loop funnels).
  No read endpoint exists for these at all.

`--discover` re-probes Roblox's API for new metrics/dimensions (run it
occasionally — Roblox adds these without announcing them); if it ever finds a
traffic-source dimension, the dashboard will have the data to use it.

## Files

| File | What |
|---|---|
| `roblox_analytics/client.py` | Open Cloud HTTP client: auth, pacing, rate-limit backoff, long-running operation polling |
| `roblox_analytics/capabilities.py` | probes which metrics/dimensions a universe supports, caches per-universe |
| `roblox_analytics/history.py` | the day-level store + "what's missing" diffing that avoids re-fetching |
| `roblox_analytics/config.py` | per-game config (universe id, catalogue, env file) |
| `roblox_analytics/export.py` | orchestrates the above into `history.json` + `export.json` |
| `dashboard/serve.py` | stdlib HTTP server, auto-discovers games, serves the dashboard |
| `dashboard/dashboard.html` | the dashboard itself (vanilla JS + Chart.js via CDN) |
