"""Unit tests for config: loading, saving, secret encryption and legacy migrations.

The autouse ``isolated_data_dir`` fixture points ``config.CONFIG_PATH`` at a
per-test temp dir, so these tests never touch the real config.json.
"""
import json
import sys
from pathlib import Path

import pytest

import config
import secretstore
# Captured before the autouse fixture replaces config.data_dir with a lambda.
from config import data_dir as real_data_dir

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_config(data):
    """Write ``data`` as JSON to the isolated config.json."""
    Path(config.CONFIG_PATH).write_text(json.dumps(data), encoding="utf-8")


def _read_raw_config():
    return Path(config.CONFIG_PATH).read_text(encoding="utf-8")


# --- load_config: defaults, merge, corruption ------------------------------------

@pytest.mark.parametrize("key, expected", [
    ("llm_provider", "anthropic"),
    ("anthropic_api_key", ""),
    ("anthropic_tokens_voice", 400),
    ("openai_model_voice", "gpt-5.6-terra"),
    ("language", "es"),
    ("offline_mode", False),
    ("window_opacity", 0.65),
])
def test_load_config_without_file_returns_defaults(key, expected):
    cfg = config.load_config()

    assert cfg[key] == expected


def test_load_config_without_file_has_no_legacy_keys():
    cfg = config.load_config()

    assert "system_prompt" not in cfg


def test_load_config_returns_independent_copy_of_defaults():
    cfg = config.load_config()
    cfg["language"] = "en"

    assert config.DEFAULTS["language"] == "es"


@pytest.mark.parametrize("key, expected", [
    ("language", "en"),           # overridden by the file
    ("window_opacity", 0.9),      # overridden by the file
    ("llm_provider", "anthropic"),  # missing from the file: default kept
    ("anthropic_tokens_vision", 2500),
])
def test_load_config_merges_partial_file_over_defaults(key, expected):
    _write_config({"language": "en", "window_opacity": 0.9})

    cfg = config.load_config()

    assert cfg[key] == expected


def test_load_config_keeps_unknown_keys_from_file():
    _write_config({"custom_flag": 7})

    cfg = config.load_config()

    assert cfg["custom_flag"] == 7


@pytest.mark.parametrize("content", ['{"language": ', "not json at all", ""])
def test_load_config_with_corrupted_json_falls_back_to_defaults(content):
    Path(config.CONFIG_PATH).write_text(content, encoding="utf-8")

    cfg = config.load_config()

    assert cfg["language"] == "es"


def test_load_config_reads_cp1252_file():
    Path(config.CONFIG_PATH).write_bytes(b'{"language": "espa\xf1ol"}')

    cfg = config.load_config()

    assert cfg["language"] == "español"


@pytest.mark.parametrize("content", ["null", "42", '"text"', "[1, 2]"])
def test_load_config_with_non_object_json_falls_back_to_defaults(content):
    Path(config.CONFIG_PATH).write_text(content, encoding="utf-8")

    cfg = config.load_config()

    assert cfg["language"] == "es"


# --- load_config: secrets ----------------------------------------------------------

def test_load_config_decrypts_protected_key():
    _write_config({"anthropic_api_key": secretstore.proteger("sk-ant-123")})

    cfg = config.load_config()

    assert cfg["anthropic_api_key"] == "sk-ant-123"


@pytest.mark.parametrize("key", ["anthropic_api_key", "openai_api_key",
                                 "assemblyai_api_key"])
def test_load_config_decrypts_every_secret_key(key):
    _write_config({key: secretstore.proteger("secret-value")})

    cfg = config.load_config()

    assert cfg[key] == "secret-value"


def test_load_config_keeps_legacy_plaintext_key():
    _write_config({"openai_api_key": "sk-plain-legacy"})

    cfg = config.load_config()

    assert cfg["openai_api_key"] == "sk-plain-legacy"


def test_load_config_blanks_undecryptable_key():
    _write_config({"anthropic_api_key": "dpapi:Z2FyYmFnZSBieXRlcyBoZXJl"})

    cfg = config.load_config()

    assert cfg["anthropic_api_key"] == ""


# --- save_config -------------------------------------------------------------------

def test_save_config_returns_true_on_success():
    result = config.save_config({"language": "en"})

    assert result is True


def test_save_config_writes_secret_with_dpapi_prefix():
    config.save_config({"anthropic_api_key": "sk-ant-secret"})

    assert '"anthropic_api_key": "dpapi:' in _read_raw_config()


def test_save_config_does_not_write_plaintext_secret():
    config.save_config({"anthropic_api_key": "sk-ant-secret"})

    assert "sk-ant-secret" not in _read_raw_config()


def test_save_config_writes_empty_secret_as_empty_string():
    config.save_config({"openai_api_key": ""})

    assert json.loads(_read_raw_config())["openai_api_key"] == ""


def test_save_config_does_not_mutate_caller_dict():
    cfg = {"anthropic_api_key": "sk-ant-secret"}

    config.save_config(cfg)

    assert cfg["anthropic_api_key"] == "sk-ant-secret"


def test_save_config_writes_non_ascii_text_verbatim():
    config.save_config({"system_prompt_es": "Habla en español"})

    assert "Habla en español" in _read_raw_config()


@pytest.mark.parametrize("key, value", [
    ("anthropic_api_key", "sk-ant-secret"),
    ("openai_api_key", "sk-openai-secret"),
    ("assemblyai_api_key", "aai-secret"),
    ("language", "en"),
    ("window_opacity", 0.3),
])
def test_save_config_round_trips_through_load_config(key, value):
    config.save_config({key: value})

    cfg = config.load_config()

    assert cfg[key] == value


def test_save_config_creates_missing_parent_dir(isolated_data_dir, monkeypatch):
    target = isolated_data_dir / "nested" / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", str(target))

    config.save_config({"language": "en"})

    assert target.is_file()


def test_save_config_returns_false_when_path_not_writable(isolated_data_dir,
                                                          monkeypatch):
    """The parent "directory" is a regular file, so nothing can be created there."""
    blocker = isolated_data_dir / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", str(blocker / "config.json"))

    result = config.save_config({"language": "en"})

    assert result is False


# --- legacy migrations -------------------------------------------------------------

def test_legacy_system_prompt_moves_to_es_when_es_is_default():
    _write_config({"system_prompt": "Old custom prompt"})

    cfg = config.load_config()

    assert cfg["system_prompt_es"] == "Old custom prompt"


def test_legacy_system_prompt_does_not_override_custom_es_prompt():
    _write_config({"system_prompt": "Old custom prompt",
                   "system_prompt_es": "New custom prompt"})

    cfg = config.load_config()

    assert cfg["system_prompt_es"] == "New custom prompt"


def test_legacy_system_prompt_key_is_removed():
    _write_config({"system_prompt": "Old custom prompt"})

    cfg = config.load_config()

    assert "system_prompt" not in cfg


def test_legacy_system_prompt_leaves_en_prompt_untouched():
    _write_config({"system_prompt": "Old custom prompt"})

    cfg = config.load_config()

    assert cfg["system_prompt_en"].startswith("You are my real-time meeting coach.")


@pytest.mark.parametrize("legacy_key, new_key", [
    ("llm_model", "anthropic_model_voice"),
    ("openai_model", "openai_model_voice"),
])
def test_legacy_model_becomes_voice_model(legacy_key, new_key):
    _write_config({legacy_key: "legacy-model-1"})

    cfg = config.load_config()

    assert cfg[new_key] == "legacy-model-1"


@pytest.mark.parametrize("legacy_key", ["llm_model", "openai_model"])
def test_legacy_model_key_is_removed(legacy_key):
    _write_config({legacy_key: "legacy-model-1"})

    cfg = config.load_config()

    assert legacy_key not in cfg


@pytest.mark.parametrize("key, expected", [
    ("anthropic_model_vision", "claude-sonnet-5"),
    ("openai_model_vision", "gpt-5.6-sol"),
])
def test_legacy_model_leaves_vision_model_at_default(key, expected):
    _write_config({"llm_model": "legacy-a", "openai_model": "legacy-o"})

    cfg = config.load_config()

    assert cfg[key] == expected


@pytest.mark.parametrize("key", ["anthropic_tokens_voice", "openai_tokens_voice"])
def test_legacy_max_tokens_becomes_voice_tokens(key):
    _write_config({"max_tokens": "800"})

    cfg = config.load_config()

    assert cfg[key] == 800


@pytest.mark.parametrize("key", ["anthropic_tokens_vision", "openai_tokens_vision"])
def test_legacy_max_tokens_leaves_vision_tokens_at_default(key):
    _write_config({"max_tokens": 800})

    cfg = config.load_config()

    assert cfg[key] == 2500


def test_legacy_max_tokens_key_is_removed():
    _write_config({"max_tokens": 800})

    cfg = config.load_config()

    assert "max_tokens" not in cfg


# --- data_dir ----------------------------------------------------------------------

def test_data_dir_from_source_is_project_folder(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    result = real_data_dir()

    assert result == str(REPO_ROOT)


def test_data_dir_frozen_uses_appdata_armony(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    result = real_data_dir()

    assert result == str(tmp_path / "Armony")


def test_data_dir_frozen_creates_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    real_data_dir()

    assert (tmp_path / "Armony").is_dir()


def test_data_dir_frozen_without_appdata_uses_program_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(config, "_HERE", str(tmp_path))

    result = real_data_dir()

    assert result == str(tmp_path / "Armony")


# --- data-loss paths found during bug analysis ------------------------------------

def test_load_config_reads_utf8_file_with_bom():
    payload = json.dumps({"language": "en",
                          "anthropic_api_key": secretstore.proteger("sk-ant-test")})
    Path(config.CONFIG_PATH).write_bytes(b"\xef\xbb\xbf" + payload.encode("utf-8"))

    cfg = config.load_config()

    assert (cfg["language"], cfg["anthropic_api_key"]) == ("en", "sk-ant-test")


def test_failed_save_keeps_previous_config_file():
    _write_config({"language": "en"})
    before = _read_raw_config()

    config.save_config({"language": "es", "bad": object()})

    assert _read_raw_config() == before


def test_failed_save_returns_false():
    assert config.save_config({"bad": object()}) is False


def test_save_leaves_no_temp_file(isolated_data_dir):
    config.save_config({"language": "en"})

    assert sorted(p.name for p in isolated_data_dir.iterdir()) == ["config.json"]


@pytest.mark.parametrize("content", ["not json at all", "", "null", "[1, 2]"])
def test_unparseable_config_is_quarantined(isolated_data_dir, content):
    Path(config.CONFIG_PATH).write_text(content, encoding="utf-8")

    config.load_config()

    assert [p.name.startswith("config.json.bad-") for p in isolated_data_dir.iterdir()] == [True]


def test_quarantined_config_keeps_original_bytes(isolated_data_dir):
    Path(config.CONFIG_PATH).write_bytes(b'{"anthropic_api_key": "dpapi:AAA", ')

    config.load_config()

    backup = next(isolated_data_dir.glob("config.json.bad-*"))
    assert backup.read_bytes() == b'{"anthropic_api_key": "dpapi:AAA", '


def test_save_after_quarantine_does_not_touch_backup(isolated_data_dir):
    Path(config.CONFIG_PATH).write_text("broken", encoding="utf-8")
    cfg = config.load_config()

    config.save_config(cfg)

    backup = next(isolated_data_dir.glob("config.json.bad-*"))
    assert backup.read_text(encoding="utf-8") == "broken"


def test_valid_config_is_not_quarantined(isolated_data_dir):
    _write_config({"language": "en"})

    config.load_config()

    assert sorted(p.name for p in isolated_data_dir.iterdir()) == ["config.json"]


@pytest.mark.parametrize("raw, expected", [
    (b"\xef\xbb\xbfprefix", "prefix"),
    ("añadir".encode("cp1252"), "añadir"),
    (b"\x81\x8d", "\x81\x8d"),
])
def test_read_user_text_decoding_fallbacks(tmp_path, raw, expected):
    path = tmp_path / "f.txt"
    path.write_bytes(raw)

    assert config.read_user_text(str(path)) == expected
