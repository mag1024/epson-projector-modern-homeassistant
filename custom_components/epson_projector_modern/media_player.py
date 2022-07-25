"""Support for Epson projector."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON, CONF_UNIQUE_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import config_validation as cv, entity_platform

from .const import DOMAIN
from .projector import Projector

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities) -> None:
    platform = entity_platform.async_get_current_platform()
    LOAD_LENS_MEMORY = "load_lens_memory"
    platform.async_register_entity_service(
        LOAD_LENS_MEMORY, { vol.Required('slot'): cv.positive_int }, LOAD_LENS_MEMORY
    )
    LOAD_IMAGE_MEMORY = "load_image_memory"
    platform.async_register_entity_service(
        LOAD_IMAGE_MEMORY, { vol.Required('slot'): cv.positive_int }, LOAD_IMAGE_MEMORY
    )

    projector = hass.data[DOMAIN][config_entry.entry_id]
    unique_id = config_entry.data[CONF_UNIQUE_ID]
    async_add_entities([EpsonProjectorMediaPlayer(projector, unique_id)])

class EpsonProjectorMediaPlayer(MediaPlayerEntity):
    """Representation of Epson Projector Device."""

    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(self, projector, unique_id):
        """Initialize entity to control Epson projector."""
        self._projector = projector
        self._unique_id = unique_id

    @property
    def device_info(self) -> DeviceInfo | None:
        """Get attributes about the device."""
        if not self._unique_id: return None
        return DeviceInfo(
            identifiers={(DOMAIN, self._unique_id)},
            manufacturer="Epson",
            model="Epson",
            name="Epson projector",
            via_device=(DOMAIN, self._unique_id),
        )

    @property
    def name(self):
        """Return the name of the device."""
        return "Epson Projector"

    @property
    def unique_id(self):
        """Return unique ID."""
        return self._unique_id

    @property
    def state(self):
        """Return the state of the device."""
        return STATE_ON if self._projector.power else STATE_OFF

    @property
    def available(self):
        """Return if projector is available."""
        return self._projector.connection_ok

    @property
    def source_list(self):
        """List of available input sources."""
        return self._projector.source_list

    @property
    def source(self):
        """Get current input sources."""
        return self._projector.source

    async def async_turn_on(self):
        """Turn on epson."""
        if self.state == STATE_OFF: await self._projector.set_power(True)

    async def async_turn_off(self):
        """Turn off epson."""
        if self.state == STATE_ON: await self._projector.set_power(False)

    async def async_select_source(self, source):
        """Select input source."""
        await self._projector.set_source(source)

    async def load_lens_memory(self, slot):
        await self._projector.load_lens_memory(slot)

    async def load_image_memory(self, slot):
        await self._projector.load_image_memory(slot)
