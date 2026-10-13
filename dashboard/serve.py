#!/usr/bin/env python3
"""Serve the analytics dashboard, auto-discovering every game that has this
module wired up.

    python3 dashboard/serve.py                      # auto-detect the games folder
    python3 dashboard/serve.py --port 8800
    python3 dashboard/serve.py --no-fetch            # skip the startup fetch
    python3 dashboard/serve.py --root ~/Games        # scan a specific folder instead

A "game" is any immediate subdirectory of the games folder containing
`scripts/analytics/config.json`. The games folder is auto-detected from where
this module itself lives — a game's `vendor/roblox_analytics` (that game's
parent folder) if vendored, or this repo's own parent folder if it's a
standalone checkout sitting next to the games — and doesn't care what any of
the folders are actually named. `--root` overrides that detection outright.

On launch (unless --no-fetch), every discovered game's `export.py` is run
once to pull any new days before the server starts, so the dashboard opens
already current. The page's own Refresh button re-fetches just the game
currently selected. Either way this only costs an API call for days not
already in that game's `history.json` — see history.py.

A game with no Open Cloud key configured yet just logs a warning and keeps
whatever (possibly empty) data it already has; it doesn't block the others.

Stdlib only; no pip install.
"""

import argparse
import json
import pathlib
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent  # wherever this clone/submodule is, whatever it's named
sys.path.insert(0, str(REPO_ROOT))  # so `roblox_analytics` (the package inside it) imports

from roblox_analytics import config as config_mod  # noqa: E402
from roblox_analytics.export import main as export_main  # noqa: E402

_fetch_locks = {}


def default_games_dir():
    """Where sibling game repos live, regardless of what anything is named.

    Vendored (REPO_ROOT sits in a folder literally named "vendor" inside a
    game): that game's own parent folder. Standalone (this repo cloned
    directly next to the games): this repo's own parent folder.
    """
    if REPO_ROOT.parent.name == "vendor":
        game_root = REPO_ROOT.parent.parent
        return game_root.parent
    return REPO_ROOT.parent


def game_entry(game_dir):
    config_dir = game_dir / "scripts" / "analytics"
    config_path = config_dir / "config.json"
    if not config_path.exists():
        return None
    cfg = config_mod.GameConfig(config_dir, config_path)
    return {
        "id": game_dir.name,
        "name": cfg.name,
        "universeId": cfg.universe_id,
        "configDir": config_dir,
        "exportPath": config_dir / "export.json",
    }


def discover_games(games_dir):
    games = []
    for candidate in sorted(games_dir.iterdir()):
        if not candidate.is_dir():
            continue
        entry = game_entry(candidate)
        if entry:
            games.append(entry)
    return games


def fetch_game(game, argv=()):
    """Run export.py's main() for one game, in-process. Never raises — a
    missing key or a network error becomes a printed warning, because one
    game's bad config shouldn't stop the others from fetching or the
    dashboard from serving whatever data already exists on disk."""
    lock = _fetch_locks.setdefault(game["id"], threading.Lock())
    if not lock.acquire(blocking=False):
        return False  # a fetch for this game is already in flight
    try:
        print(f"\n--- {game['name']} ---")
        export_main(game["configDir"], argv=list(argv))
        return True
    except SystemExit as err:
        print(f"  ! {game['name']}: {err}")
        return False
    except Exception as err:  # noqa: BLE001 — this is a best-effort background refresh
        print(f"  ! {game['name']}: {err}")
        return False
    finally:
        lock.release()


def make_handler(games_by_id):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # keep the terminal quiet; errors still raise

        def _json(self, payload, status=200):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_data(self, game_id):
            game = games_by_id.get(game_id)
            if not game or not game["exportPath"].exists():
                self._json({"error": f"no export.json for '{game_id}' — run export.py first"}, 404)
                return
            self._json(json.loads(game["exportPath"].read_text()))

        def do_GET(self):
            path = urllib.parse.urlsplit(self.path).path

            if path == "/" or path == "/index.html":
                html = (HERE / "dashboard.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return

            if path == "/api/games":
                self._json([{"id": g["id"], "name": g["name"], "universeId": g["universeId"]}
                            for g in games_by_id.values()])
                return

            if path.startswith("/api/refresh/"):
                game_id = path.removeprefix("/api/refresh/")
                game = games_by_id.get(game_id)
                if not game:
                    self._json({"error": f"unknown game '{game_id}'"}, 404)
                    return
                fetch_game(game)
                self._serve_data(game_id)
                return

            if path.startswith("/api/data/"):
                self._serve_data(path.removeprefix("/api/data/"))
                return

            self.send_response(404)
            self.end_headers()

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=pathlib.Path, default=None,
                        help="folder to scan for game subfolders (default: auto-detected)")
    parser.add_argument("--port", type=int, default=8800)
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip the startup fetch and serve whatever export.json already has")
    args = parser.parse_args()

    games_dir = args.root or default_games_dir()
    games = discover_games(games_dir)
    if not games:
        raise SystemExit(f"no games found under {games_dir} — each needs "
                          f"scripts/analytics/config.json (pass --root to point elsewhere)")

    print(f"\nfound {len(games)} game(s) under {games_dir}:")
    for g in games:
        print(f"  {g['id']}  (universe {g['universeId']})")

    if not args.no_fetch:
        print("\nfetching latest data before serving (pass --no-fetch to skip this)...")
        for g in games:
            fetch_game(g)
    else:
        print("\n--no-fetch: serving whatever is already on disk")

    games_by_id = {g["id"]: g for g in games}
    print(f"\nhttp://localhost:{args.port}\n")

    server = ThreadingHTTPServer(("localhost", args.port), make_handler(games_by_id))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
