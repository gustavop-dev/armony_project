"""Settings of the removed offline (Whisper) mode are purged on load."""
import json

import config


def test_defaults_have_no_offline_keys():
    assert not set(config.OBSOLETAS) & set(config.DEFAULTS)


def test_load_drops_obsolete_keys_and_keeps_the_rest(isolated_data_dir):
    stored = {k: "legacy" for k in config.OBSOLETAS}
    stored["silence_hang"] = 1.2
    with open(config.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(stored, f)

    cfg = config.load_config()

    assert not set(config.OBSOLETAS) & set(cfg)
    assert cfg["silence_hang"] == 1.2
