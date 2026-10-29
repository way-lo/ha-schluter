"""Shared entity helpers for Schluter integration."""
from __future__ import annotations

from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import FOLLOWUP_REFRESH_DELAYS


class SchluterEntity(CoordinatorEntity):
    """Base entity that provides consistent availability semantics."""

    def __init__(self, coordinator, thermostat_id: str) -> None:
        super().__init__(coordinator)
        self._thermostat_id = thermostat_id
        self._followup_cancels: list = []

    @property
    def available(self) -> bool:
        """Return True only when coordinator and device are available."""
        obj = self.coordinator.data.get(self._thermostat_id)
        return (
            self.coordinator.last_update_success
            and obj is not None
            and getattr(obj, "is_online", True)
        )

    async def async_refresh_after_command(self) -> None:
        """Refresh now, then again shortly after.

        The cloud applies a command immediately, but the thermostat reports
        its new set point later, so one immediate refresh often shows stale
        values until the next regular poll.
        """
        await self.coordinator.async_request_refresh()
        self._schedule_followup_refreshes()

    def _schedule_followup_refreshes(self) -> None:
        self._cancel_followup_refreshes()
        for delay in FOLLOWUP_REFRESH_DELAYS:
            self._followup_cancels.append(
                async_call_later(self.hass, delay, self._async_followup_refresh)
            )

    async def _async_followup_refresh(self, _now) -> None:
        await self.coordinator.async_request_refresh()

    def _cancel_followup_refreshes(self) -> None:
        for cancel in self._followup_cancels:
            cancel()
        self._followup_cancels.clear()

    async def async_will_remove_from_hass(self) -> None:
        """Cancel pending follow-up refreshes."""
        self._cancel_followup_refreshes()
        await super().async_will_remove_from_hass()
