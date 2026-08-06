import pytest

from app.config import ConfigError, Settings, reload_settings


def test_defaults_when_env_is_empty():
    settings = Settings.from_env({})
    assert settings.rate_limit_enabled is True
    assert settings.rate_limit_chat_max_requests == 10
    assert settings.rate_limit_chat_window_seconds == 60
    assert settings.redis_url is None


def test_reads_values_from_env():
    settings = Settings.from_env(
        {
            "RATE_LIMIT_ENABLED": "false",
            "RATE_LIMIT_CHAT_MAX_REQUESTS": "25",
            "RATE_LIMIT_CHAT_WINDOW_SECONDS": "120",
            "REDIS_URL": "redis://localhost:6379/0",
            "TRUST_PROXY_HEADERS": "yes",
            "TRUSTED_PROXIES": "10.0.0.1, 10.0.0.2",
        }
    )
    assert settings.rate_limit_enabled is False
    assert settings.rate_limit_chat_max_requests == 25
    assert settings.rate_limit_chat_window_seconds == 120
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.trust_proxy_headers is True
    assert settings.trusted_proxies == ("10.0.0.1", "10.0.0.2")


@pytest.mark.parametrize(
    "env",
    [
        {"RATE_LIMIT_CHAT_MAX_REQUESTS": "0"},
        {"RATE_LIMIT_CHAT_MAX_REQUESTS": "-3"},
        {"RATE_LIMIT_CHAT_MAX_REQUESTS": "ten"},
        {"RATE_LIMIT_CHAT_WINDOW_SECONDS": "0"},
        {"RATE_LIMIT_CHAT_WINDOW_SECONDS": "abc"},
        {"RATE_LIMIT_ENABLED": "maybe"},
        {"REDIS_TIMEOUT_SECONDS": "0"},
    ],
)
def test_invalid_values_rejected(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_reload_settings_uses_provided_mapping():
    settings = reload_settings({"RATE_LIMIT_CHAT_MAX_REQUESTS": "3"})
    assert settings.rate_limit_chat_max_requests == 3
    reload_settings({})
