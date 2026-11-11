"""Set up the Local First Conversation integration."""

from awesomeversion import AwesomeVersion
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv

DOMAIN = "local_first_conversation"
CONF_FALLBACK = "fallback_agent"
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a router."""
    if AwesomeVersion(HA_VERSION) < AwesomeVersion("2026.11.1"):
        raise ConfigEntryError(
            "Local First Conversation requires Home Assistant 2026.11.1 or newer"
        )
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.CONVERSATION])
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply a changed fallback."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a router."""
    return await hass.config_entries.async_unload_platforms(
        entry, [Platform.CONVERSATION]
    )
