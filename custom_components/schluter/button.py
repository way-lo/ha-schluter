"""Button entities for Schluter thermostats."""
from __future__ import annotations

from aiohttp.client_exceptions import ClientConnectorError
from aioschluter import ApiError, InvalidSessionIdError, InvalidUserPasswordError
from aioschluter.const import REGULATION_MODE_SCHEDULE

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError

from . import SchluterData
from .const import DOMAIN
from .entity import SchluterEntity


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add a "Resume schedule" button for each thermostat."""
    data: SchluterData = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        SchluterResumeScheduleButton(data.api, data.coordinator, thermostat_id)
        for thermostat_id in data.coordinator.data
    )


class SchluterResumeScheduleButton(SchluterEntity, ButtonEntity):
    """Return the thermostat to its programmed schedule."""

    _attr_icon = "mdi:calendar-refresh"

    def __init__(self, api, coordinator, thermostat_id: str) -> None:
        super().__init__(coordinator, thermostat_id)
        self._api = api
        thermostat = coordinator.data[thermostat_id]
        self._serial_number = thermostat.serial_number
        self._attr_name = f"{thermostat.name} Resume schedule"
        self._attr_unique_id = f"{thermostat.serial_number}_resume_schedule"

    @property
    def device_info(self):
        """Attach to the same device as the climate entity."""
        return {"identifiers": {(DOMAIN, self._thermostat_id)}}

    async def async_press(self) -> None:
        """Switch the thermostat back to schedule mode."""
        try:
            await self._api.async_set_regulation_mode(
                self._api.sessionid, self._serial_number, REGULATION_MODE_SCHEDULE
            )
        except (InvalidUserPasswordError, InvalidSessionIdError) as err:
            raise ConfigEntryAuthFailed from err
        except (ApiError, ClientConnectorError) as err:
            raise HomeAssistantError(f"Could not resume schedule: {err}") from err
        await self.coordinator.async_request_refresh()
