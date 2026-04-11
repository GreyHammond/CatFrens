import json
import os
from config import GUILD_SETTINGS_FILE, DEFAULT_FACT_INTERVAL_HOURS, DEFAULT_PULL_COOLDOWN_MINUTES

def load_guild_settings() -> dict:
    if os.path.exists(GUILD_SETTINGS_FILE):
        with open(GUILD_SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_guild_settings(settings: dict):
    with open(GUILD_SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

def get_guild_cfg(settings: dict, guild_id: int) -> dict:
    key = str(guild_id)
    if key not in settings:
        settings[key] = _default_cfg()
        save_guild_settings(settings)
    return settings[key]

def save_guild_cfg(settings: dict, guild_id: int, cfg: dict):
    settings[str(guild_id)] = cfg
    save_guild_settings(settings)

def _default_cfg() -> dict:
    return {
        "fact_channels":       [],
        "motd_channels":       [],
        "fact_interval_hours": DEFAULT_FACT_INTERVAL_HOURS,
        "command_channels":    [],
        "excluded_channels":   [],
        "allowed_roles":       [],
        "excluded_roles":      [],
        "cooldowns": {
            "default": DEFAULT_PULL_COOLDOWN_MINUTES,
            "roles":   {},
        },
    }
