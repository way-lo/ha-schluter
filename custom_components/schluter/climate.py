"""Support for Schluter DITRA-HEAT-E-WIFI Thermostats."""
from __future__ import annotations

import logging

from aiohttp.client_exceptions import ClientConnectorError
from aioschluter import (
    ApiError,
    InvalidSessionIdError,
    InvalidUserPasswordError,
    SchluterApi,
    Thermostat,
)

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import SchluterData
from .const import (
    DOMAIN,
    MODE_PERMANENT_HOLD,
    MODE_SCHEDULE,
    MODE_TEMPORARY_HOLD,
    PRESET_PERMANENT,
    PRESET_SCHEDULE,
    PRESET_TEMPORARY,
)
from .entity import SchluterEntity

_LOGGER = logging.getLogger(__name__)

_PRESET_TO_MODE = {
    PRESET_SCHEDULE: MODE_SCHEDULE,
    PRESET_TEMPORARY: MODE_TEMPORARY_HOLD,
    PRESET_PERMANENT: MODE_PERMANENT_HOLD,
}
_MODE_TO_PRESET = {mode: preset for preset, mode in _PRESET_TO_MODE.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up device tracker for DITRA-HEAT-E-WIFI component."""
    data: SchluterData = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        SchluterThermostat(data.api, data.coordinator, thermostat_id)
        for thermostat_id in data.coordinator.data
    )


class SchluterThermostat(SchluterEntity, ClimateEntity):
    """Define an Schluter Thermostat Entity.

    HVAC modes: Auto = follow the schedule, Heat = hold (use the presets to
    pick Temporary or Permanent). The thermostat has no remote "off".
    """

    _attr_hvac_modes = [HVACMode.AUTO, HVACMode.HEAT]
    _attr_preset_modes = [PRESET_SCHEDULE, PRESET_TEMPORARY, PRESET_PERMANENT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )
    _enable_turn_on_off_backwards_compatibility: bool = False

    coordinator: DataUpdateCoordinator[dict[str, dict[str, Thermostat]]]

    def __init__(
        self,
        api: SchluterApi,
        coordinator: DataUpdateCoordinator[dict[str, dict[str, Thermostat]]],
        thermostat_id: str,
    ) -> None:
        """Initialize Schluter Thermostat."""
        super().__init__(coordinator, thermostat_id)
        self._api = api
        self._name = coordinator.data[thermostat_id].name
        self._attr_unique_id = thermostat_id
        self._serial_number = coordinator.data[thermostat_id].serial_number
        ClimateEntity.__init__(self)

    @property
    def _thermostat(self) -> Thermostat:
        return self.coordinator.data[self._attr_unique_id]

    @property
    def device_info(self):
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._attr_unique_id)},
            "name": self._name,
            "sw_version": self._thermostat.sw_version,
            "model": "DITRA-HEAT-E-Wifi",
            "manufacturer": "Schluter",
        }

    @property
    def hvac_mode(self):
        """Auto while following the schedule, Heat while holding."""
        if self._thermostat.regulation_mode == MODE_SCHEDULE:
            return HVACMode.AUTO
        return HVACMode.HEAT

    @property
    def preset_mode(self):
        """Schedule, Temporary hold or Permanent hold."""
        return _MODE_TO_PRESET.get(self._thermostat.regulation_mode)

    @property
    def unique_id(self):
        """Return unique ID for this device."""
        return self._serial_number

    @property
    def name(self):
        """Return the name of the thermostat."""
        return self._name

    @property
    def temperature_unit(self):
        """Schluter API always uses celsius."""
        return UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._thermostat.temperature

    @property
    def hvac_action(self) -> HVACAction:
        """Return current operation. Can only be heating or idle."""
        if self._thermostat.is_heating:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def target_temperature(self):
        """Return the temperature the thermostat is aiming for.

        The cloud's set point lags behind a mode change, so in a hold we read
        the stored hold temperature directly (hundredths of a degree C).
        """
        thermostat = self._thermostat
        mode = thermostat.regulation_mode
        raw = None
        if mode == MODE_TEMPORARY_HOLD:
            raw = getattr(thermostat, "_comfort_temperature", None)
        elif mode == MODE_PERMANENT_HOLD:
            raw = getattr(thermostat, "_manual_temp", None)
        if raw is None:
            return thermostat.set_point_temp
        return round(raw / 100, 2)

    @property
    def min_temp(self):
        """Identify min_temp in Schluter API."""
        return self._thermostat.min_temp

    @property
    def max_temp(self):
        """Identify max_temp in Schluter API."""
        return self._thermostat.max_temp

    @property
    def extra_state_attributes(self):
        """Diagnostic attributes (degrees C, as reported by the cloud)."""
        t = self._thermostat

        def _c(raw):
            """Raw API temps are hundredths of a degree C."""
            return None if raw is None else round(raw / 100, 2)

        return {
            "regulation_mode": t.regulation_mode,
            "manual_temperature_c": _c(getattr(t, "_manual_temp", None)),
            "comfort_temperature_c": _c(getattr(t, "_comfort_temperature", None)),
            "comfort_end_time": getattr(t, "_comfort_end_time", None),
            "set_point_temperature_c": t.set_point_temp,
            "vacation_enabled": getattr(t, "_vacation_enabled", None),
            "vacation_temperature_c": _c(getattr(t, "_vacation_temperature", None)),
        }

    async def _async_send(self, call) -> None:
        """Run an API call, translating errors, then refresh."""
        try:
            await call()
        except (InvalidUserPasswordError, InvalidSessionIdError) as err:
            raise ConfigEntryAuthFailed from err
        except (ApiError, ClientConnectorError) as err:
            raise HomeAssistantError(f"Schluter request failed: {err}") from err
        await self.async_refresh_after_command()

    async def _async_set_mode(self, mode: int) -> None:
        _LOGGER.debug("Setting regulation mode of %s to %s", self._name, mode)
        await self._async_send(
            lambda: self._api.async_set_regulation_mode(
                self._api.sessionid, self._serial_number, mode
            )
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Auto = schedule, Heat = temporary hold."""
        if hvac_mode == HVACMode.AUTO:
            await self._async_set_mode(MODE_SCHEDULE)
        elif hvac_mode == HVACMode.HEAT:
            await self._async_set_mode(MODE_TEMPORARY_HOLD)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Choose schedule, temporary hold or permanent hold."""
        await self._async_set_mode(_PRESET_TO_MODE[preset_mode])

    async def async_set_temperature(self, **kwargs):
        """Set a permanent hold at the given temperature."""
        target_temp = kwargs.get(ATTR_TEMPERATURE)
        if target_temp is None:
            return
        _LOGGER.debug("Setting permanent hold temperature: %s", target_temp)
        # The library truncates temp * 100 to an int; avoid float error such
        # as 14.999999 -> 1499.
        adjusted = (round(target_temp * 100) + 0.5) / 100
        await self._async_send(
            lambda: self._api.async_set_temperature(
                self._api.sessionid, self._serial_number, adjusted
            )
        )
