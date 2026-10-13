#!/usr/bin/env python3
"""Serve the analytics dashboard, auto-discovering every game that has this
module wired up.

    python3 vendor/roblox_analytics/dashboard/serve.py
    python3 vendor/roblox_analytics/dashboard/serve.py --root ~/Projects/Games --port 8800

A "game" is any immediate subdirectory of `--root` containing
`scripts/analytics/config.json`. Each one shows up in the dashboard's universe
switcher, reading straight from that game's `scripts/analytics/export.json` —
nothing is copied or uploaded anywhere, this only serves files already on disk.

Stdlib only; no pip install. Run `export.py` first (or via cron) to populate
the data this serves.
"""

import argparse
import json
import pathlib
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent


def find_default_root():
    """vendor/roblox_analytics/dashboard/serve.py -> the folder of sibling game
    repos, if there is one; else the single game repo this is vendored into."""
    vendored_in = HERE.parents[2]  # .../<game>/vendor/roblox_analytics
    games_root = vendored_in.parent
    if any((d / "scripts" / "analytics" / "config.json").exists()
           for d in games_root.iterdir() if d.is_dir()):
        return games_root
    return vendored_in.parent if vendored_in.name == "vendor" else vendored_in


def discover_games(root):
    games = []
    for game_dir in sorted(root.iterdir()):
        config_path = game_dir / "scripts" / "analytics" / "config.json"
        if not config_path.exists():
            continue
        try:
            config = json.loads(config_path.read_text())
        except ValueError:
            continue
        games.append({
            "id": game_dir.name,
            "name": config.get("game", game_dir.name),
            "universeId": config.get("universeId"),
            "exportPath": game_dir / "scripts" / "analytics" / "export.json",
        })
    return games


def make_handler(root):
    games_by_id = {g["id"]: g for g in discover_games(root)}

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

            if path.startswith("/api/data/"):
                game_id = path.removeprefix("/api/data/")
                game = games_by_id.get(game_id)
                if not game or not game["exportPath"].exists():
                    self._json({"error": f"no export.json for '{game_id}' — run export.py first"}, 404)
                    return
                self._json(json.loads(game["exportPath"].read_text()))
                return

            self.send_response(404)
            self.end_headers()

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=pathlib.Path, default=None,
                        help="folder containing one subfolder per game (default: auto-detected)")
    parser.add_argument("--port", type=int, default=8800)
    args = parser.parse_args()

    root = args.root or find_default_root()
    games = discover_games(root)
    if not games:
        raise SystemExit(f"no games found under {root} — each needs scripts/analytics/config.json")

    print(f"serving {len(games)} game(s) from {root}:")
    for g in games:
        print(f"  {g['id']}  (universe {g['universeId']})")
    print(f"\nhttp://localhost:{args.port}\n")

    server = ThreadingHTTPServer(("localhost", args.port), make_handler(root))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
