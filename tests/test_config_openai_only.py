"""OpenAI is the only answer provider; stored Anthropic settings are preserved."""
import json

import config
import secretstore


def test_defaults_are_openai_only():
    assert not [k for k in config.DEFAULTS if k.startswith("anthropic_")]
    assert "llm_provider" not in config.DEFAULTS
    assert config.DEFAULTS["openai_model"] == "gpt-6.1-sol"
    assert "openai_model_voice" not in config.DEFAULTS
    assert "openai_model_vision" not in config.DEFAULTS


def test_stored_anthropic_key_survives_load_and_save_unchanged(isolated_data_dir):
    stored_anthropic = secretstore.PREFIJO + "opaque-ciphertext"
    with open(config.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"llm_provider": "anthropic",
                   "anthropic_api_key": stored_anthropic,
                   "anthropic_model_voice": "claude-haiku-4-5",
                   "openai_tokens_voice": 1000}, f)

    cfg = config.load_config()
    assert cfg["anthropic_api_key"] == stored_anthropic      # never decrypted
    assert cfg["openai_tokens_voice"] == 1000               # user choice kept
    assert config.save_config(cfg)

    with open(config.CONFIG_PATH, encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["anthropic_api_key"] == stored_anthropic
    assert on_disk["anthropic_model_voice"] == "claude-haiku-4-5"


def test_saved_per_use_models_are_dropped_for_the_single_model(isolated_data_dir):
    with open(config.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"openai_model_voice": "gpt-5.6-terra",
                   "openai_model_vision": "gpt-5.4-mini", "max_tokens": 300}, f)

    cfg = config.load_config()
    assert cfg["openai_model"] == "gpt-6.1-sol"
    assert "openai_model_voice" not in cfg and "openai_model_vision" not in cfg
    assert cfg["openai_tokens_voice"] == 300 and "max_tokens" not in cfg
