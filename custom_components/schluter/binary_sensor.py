"""Binary sensors for Schluter thermostats: heating and online."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SchluterData
from .const import DOMAIN
from .entity import SchluterEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the heating and online sensors."""
    data: SchluterData = hass.data[DOMAIN][config_entry.entry_id]
    entities: list[BinarySensorEntity] = []
    for thermostat_id in data.coordinator.data:
        entities.append(SchluterHeatingSensor(data.coordinator, thermostat_id))
        entities.append(SchluterOnlineSensor(data.coordinator, thermostat_id))
    async_add_entities(entities)


class _SchluterBinarySensor(SchluterEntity, BinarySensorEntity):
    """Common setup for the thermostat binary sensors."""

    _suffix = ""
    _label = ""

    def __init__(self, coordinator, thermostat_id: str) -> None:
        super().__init__(coordinator, thermostat_id)
        thermostat = coordinator.data[thermostat_id]
        self._attr_name = f"{thermostat.name} {self._label}"
        self._attr_unique_id = f"{thermostat.serial_number}_{self._suffix}"

    @property
    def _thermostat(self):
        return self.coordinator.data[self._thermostat_id]

    @property
    def device_info(self):
        """Attach to the same device as the climate entity."""
        return {"identifiers": {(DOMAIN, self._thermostat_id)}}


class SchluterHeatingSensor(_SchluterBinarySensor):
    """On while the floor is actively heating."""

    _suffix = "heating"
    _label = "Heating"
    # No device class: "heat" would label the states Hot/Normal instead of On/Off.
    _attr_icon = "mdi:fire"

    @property
    def is_on(self) -> bool:
        return bool(self._thermostat.is_heating)


class SchluterOnlineSensor(_SchluterBinarySensor):
    """On while the thermostat is connected to the Schluter cloud."""

    _suffix = "online"
    _label = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def available(self) -> bool:
        # Stay available when the thermostat is offline: that is the state.
        return self.coordinator.last_update_success and (
            self._thermostat_id in self.coordinator.data
        )

    @property
    def is_on(self) -> bool:
        return bool(self._thermostat.is_online)
