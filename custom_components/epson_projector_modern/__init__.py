"""The epson integration."""
import asyncio
import logging

from .projector import Projector

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PLATFORMS = [Platform.MEDIA_PLAYER]

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up epson from a config entry."""
    projector = Projector(entry.data[CONF_HOST])
    try:
        await projector.connect()
    except asyncio.exceptions.TimeoutError:
        _LOGGER.warning("Initial projector connection timed out...")
    except:
        logging.exception("Initial projector connection failed")
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = projector
    hass.config_entries.async_setup_platforms(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok: hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
