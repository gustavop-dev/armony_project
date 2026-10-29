"""API keys for the harness: env var first, then the app's config.json."""
import json
import os


def read_key(field, env_var):
    """Env var, else ``field`` from the source checkout's config.json, else from
    the one the installed .exe keeps in %APPDATA%\\Armony (see config.data_dir).
    Stored values are DPAPI-protected; they are decrypted here."""
    key = os.environ.get(env_var)
    if key:
        return key
    import config
    import secretstore
    candidates = [config.CONFIG_PATH]
    if os.environ.get("APPDATA"):
        candidates.append(os.path.join(os.environ["APPDATA"], "Armony", "config.json"))
    for path in candidates:
        try:
            with open(path, encoding="utf-8") as f:
                stored = json.load(f).get(field) or ""
        except (OSError, ValueError):
            continue
        key = secretstore.revelar(stored)
        if key:
            return key
    return ""
