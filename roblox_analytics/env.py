"""Open Cloud API key lookup, shared by every tool in this package.

Deliberately minimal: no interpolation, no multi-line values, no pip install.
Environment wins over any file so a one-off `ROBLOX_API_KEY=... export.py` can
hit a different universe without editing anything on disk.
"""

import os
import pathlib

KEY_NAMES = ("ROBLOX_OPEN_CLOUD_KEY", "ROBLOX_API_KEY")
ENV_FILES = (".env.local", ".env")


def read_env_file(path):
    values = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        name, sep, value = line.partition("=")
        if not sep:
            continue
        values[name.strip()] = value.strip().strip("'\"")
    return values


def find_api_key(root, env_file=None):
    """The Open Cloud key: real environment first, then a .env file under `root`."""
    for name in KEY_NAMES:
        if os.environ.get(name):
            return os.environ[name], f"${name}"

    candidates = [pathlib.Path(env_file)] if env_file else [pathlib.Path(root) / f for f in ENV_FILES]
    for path in candidates:
        values = read_env_file(path)
        for name in KEY_NAMES:
            if values.get(name):
                return values[name], f"{name} in {path.name}"

    raise SystemExit(
        f"no Open Cloud key: set {' or '.join(KEY_NAMES)} in the environment, "
        f"or in {root}/.env.local (needs the universe-analytics:read scope)"
    )
