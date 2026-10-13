"""Per-game config: where its universe id, data files and catalogue live.

One `config.json` per game, checked in next to its `history.json`. Paths in it
are relative to the config file's own directory.
"""

import json


class GameConfig:
    def __init__(self, config_dir, config_path):
        self.dir = config_dir
        data = json.loads(config_path.read_text()) if config_path.exists() else {}
        self._data = data

        self.name = data.get("game", config_dir.parent.parent.name)
        self.universe_id = data.get("universeId")
        self.root = (config_dir / "../..").resolve()
        # Paths to sibling game repos, relative to THIS repo's root (e.g. "../escape_a_black_hole")
        # — how the dashboard finds other games without assuming a shared parent folder on disk.
        self.siblings = data.get("siblings", [])
        self.env_file = (config_dir / data["envFile"]).resolve() if data.get("envFile") else None
        self.catalogue_file = (config_dir / data["catalogueFile"]).resolve() if data.get("catalogueFile") else None
        self.ids_file = (config_dir / data["idsFile"]).resolve() if data.get("idsFile") else None

    def require_universe_id(self):
        if self.universe_id:
            return self.universe_id
        raise SystemExit(
            f"no universeId in {self.dir}/config.json — add one (Creator Dashboard "
            f"URL, or Open Cloud), not the place id"
        )


def monetisation_context(cfg):
    """The catalogue, so revenue has prices to be read against.

    Best-effort and entirely optional: a game with no monetisation sync just
    gets a note instead of a crash.
    """
    if not cfg.catalogue_file or not cfg.catalogue_file.exists():
        return {"note": "no catalogue configured for this game"}
    try:
        catalogue = json.loads(cfg.catalogue_file.read_text())
    except ValueError as err:
        return {"note": f"catalogue unreadable: {err}"}

    ids = {}
    if cfg.ids_file and cfg.ids_file.exists():
        try:
            ids = json.loads(cfg.ids_file.read_text()).get("items", {})
        except ValueError:
            pass

    items = {}
    for kind, entries in catalogue.items():
        if not isinstance(entries, dict):
            continue
        for key, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            items[key] = {
                "kind": kind,
                "name": entry.get("name"),
                "priceRobux": entry.get("price"),
                "forSale": entry.get("forSale", True),
                "id": (ids.get(key) or {}).get("id") if isinstance(ids.get(key), dict) else ids.get(key),
            }
    return {
        "note": "What is on sale. Which of these actually sold cannot be split out — see notAvailable.perProductRevenue.",
        "items": items,
    }
