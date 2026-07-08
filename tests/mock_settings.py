from types import SimpleNamespace


def api_settings_namespace(**overrides):
    """Minimal Settings stand-in for tests that mock api.main.get_settings."""
    defaults = {
        "qdrant_collection_name": "JOBS_ON_THE_HUB",
        "chat_question_max_length": 500,
        "chat_rate_limit": "10/minute",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)
