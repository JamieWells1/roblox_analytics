# roblox_analytics

Reusable Roblox Open Cloud analytics export + dashboard, shared across games
rather than copy-pasted into each one. Used by `build_a_galaxy` and
`escape_a_black_hole` as a **standalone clone sitting next to them** — e.g. a
`roblox/` folder containing `roblox_analytics`, `build_a_galaxy` and
`escape_a_black_hole` as three siblings, cloned once rather than vendored as a
git submodule in each game. That means updating this module is a plain `git
pull` in this one repo — no pointer commit needed in every game that uses it.
(A `vendor/roblox_analytics` submodule also still works if you'd rather pin a
version per game; both layouts are auto-detected and nothing cares what any
of the folders are actually named.)

Pulls DAU/MAU, retention, revenue, paying users, CVR, ARPPU, session length
and playtime for a universe, keeps an ever-growing day-by-day history on disk
(Roblox's own API only serves a 28-day rolling window), and serves an
interactive Grafana-style dashboard over it with a universe switcher.

## Wiring a game up

1. Clone this repo as a sibling of the game repo(s) — not inside any of them:
   ```
   cd ~/Projects/Games   # whatever folder already contains your game repos
   git clone https://github.com/JamieWells1/roblox_analytics.git
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
3. Create the shim at `scripts/analytics/export.py` — copy it from
   `build_a_galaxy` or `escape_a_black_hole`'s copy verbatim; it searches for
   this module (vendored or standalone) at runtime, so it never needs editing
   per game.
4. Run it: `python3 scripts/analytics/export.py`. The Open Cloud key comes
   from `ROBLOX_OPEN_CLOUD_KEY` / `ROBLOX_API_KEY` in the environment or
   `.env.local`, and needs the `universe-analytics:read` scope.

Commit `scripts/analytics/history.json`, `export.json` and
`capabilities.json` — that's what makes the "only fetch new days" logic work
across machines and over time, and what the dashboard reads.

## Running the dashboard

```
python3 dashboard/serve.py                            # standalone layout (recommended)
python3 vendor/roblox_analytics/dashboard/serve.py    # vendored layout
```

Auto-detects the folder containing the game repos (that game's own parent
folder if vendored, or this repo's own parent folder if standalone), scans it
for every immediate subfolder with a `scripts/analytics/config.json`, fetches
each one's latest data, then serves a page to switch between them — no manual
wiring beyond step 1-4 above, and no need to run `export.py` separately first.
Open http://localhost:8800.

- `--no-fetch` skips the startup fetch and serves whatever's already on disk.
- The page's own **Refresh** button re-fetches just the game currently selected.
- `--root <folder>` scans that folder instead of the auto-detected one.

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
