"""Number entities for Schluter thermostats."""
from __future__ import annotations

from aiohttp.client_exceptions import ClientConnectorError, ClientError
from aioschluter import InvalidSessionIdError
from aioschluter.const import API_SET_THERMOSTAT_URL, HTTP_OK, HTTP_UNAUTHORIZED

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import SchluterData
from .const import DOMAIN
from .entity import SchluterEntity


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add an "Energy price" number for each thermostat."""
    data: SchluterData = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        SchluterEnergyPriceNumber(data.api, data.coordinator, thermostat_id)
        for thermostat_id in data.coordinator.data
    )


def format_price(value: float) -> str:
    """Format a price the way the Schluter web portal sends it: "0.12"."""
    return f"{round(value, 4):.4f}".rstrip("0").rstrip(".") or "0"


class SchluterEnergyPriceNumber(SchluterEntity, NumberEntity):
    """The energy tariff stored on the thermostat ($/kWh).

    This is the same value as the "Energy Tariff" box on the Schluter web
    portal. The cloud applies it to all past usage as well, not only to
    energy used from now on, so changing it rewrites the cost the Schluter
    app and portal show for earlier days.

    The cloud accepts up to four decimals, but the thermostat itself keeps
    only two and truncates (0.0893 becomes 0.08, not 0.09). It writes its own
    copy back to the cloud at its next schedule transition, so use two
    decimals.
    """

    _attr_icon = "mdi:currency-usd"
    _attr_native_unit_of_measurement = "$/kWh"
    _attr_native_min_value = 0
    _attr_native_max_value = 5
    _attr_native_step = 0.01
    _attr_mode = NumberMode.BOX

    def __init__(self, api, coordinator, thermostat_id: str) -> None:
        super().__init__(coordinator, thermostat_id)
        self._api = api
        thermostat = coordinator.data[thermostat_id]
        self._serial_number = thermostat.serial_number
        self._attr_name = f"{thermostat.name} Energy price"
        self._attr_unique_id = f"{thermostat.serial_number}_energy_price"

    @property
    def device_info(self):
        """Attach to the same device as the climate entity."""
        return {"identifiers": {(DOMAIN, self._thermostat_id)}}

    @property
    def native_value(self) -> float | None:
        """Return the price stored on the thermostat."""
        return self.coordinator.data[self._thermostat_id].kwh_charge

    async def async_set_native_value(self, value: float) -> None:
        """Send a new price to the Schluter cloud."""
        thermostat = self.coordinator.data[self._thermostat_id]
        session_id = self._api.sessionid
        if not session_id:
            raise ConfigEntryAuthFailed("No Schluter session")
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                API_SET_THERMOSTAT_URL,
                params={"sessionId": session_id, "serialnumber": self._serial_number},
                json={"Room": thermostat.name, "KwhCharge": format_price(value)},
            ) as resp:
                if resp.status == HTTP_UNAUTHORIZED:
                    raise InvalidSessionIdError("Expired Schluter session")
                if resp.status != HTTP_OK:
                    raise HomeAssistantError(
                        f"Could not set the energy price: HTTP {resp.status}"
                    )
                result = await resp.json(content_type=None)
        except InvalidSessionIdError as err:
            raise ConfigEntryAuthFailed from err
        except (ClientConnectorError, ClientError) as err:
            raise HomeAssistantError(f"Could not set the energy price: {err}") from err
        if isinstance(result, dict) and result.get("Success") is False:
            raise HomeAssistantError("The Schluter cloud rejected the energy price")
        await self.async_refresh_after_command()
