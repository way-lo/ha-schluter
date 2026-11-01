"""Near-instant updates for Schluter thermostats via long-polling.

The Schluter cloud offers a notification endpoint: a GET request that the
server holds open (about a minute) and answers as soon as a thermostat
changes, with the full new state of that thermostat. When nothing changed it
answers with an empty result, and we simply ask again.

The server only queues notifications for a session after that session has
fetched the thermostat list, so a new session is first subscribed with a
normal refresh.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from aioschluter import Thermostat
from aioschluter.const import API_BASE_URL, HTTP_OK, HTTP_UNAUTHORIZED
from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import (
    PUSH_POLL_INTERVAL,
    PUSH_RECONNECT_MAX_DELAY,
    PUSH_RECONNECT_MIN_DELAY,
    PUSH_REQUEST_TIMEOUT,
    UPDATE_INTERVAL,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from . import SchluterDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

NOTIFICATION_URL = API_BASE_URL + "/api/notification"


class SchluterPushClient:
    """Long-poll the notification endpoint and feed changes to the coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: ClientSession,
        coordinator: SchluterDataUpdateCoordinator,
    ) -> None:
        self._hass = hass
        self._session = session
        self._coordinator = coordinator
        # The coordinator's first refresh already subscribed its session.
        self._subscribed_session: str | None = coordinator.api_sessionid
        self._connected = False

    def start(self, entry: ConfigEntry) -> None:
        """Start listening; the task is cancelled when the entry unloads."""
        entry.async_create_background_task(
            self._hass, self._run(), f"{entry.domain} push {entry.entry_id}"
        )

    def _set_connected(self, connected: bool) -> None:
        """Poll rarely while push works, normally while it does not."""
        if connected == self._connected:
            return
        self._connected = connected
        minutes = PUSH_POLL_INTERVAL if connected else UPDATE_INTERVAL
        self._coordinator.update_interval = timedelta(minutes=minutes)
        _LOGGER.debug("Push updates %s", "connected" if connected else "lost")

    async def _run(self) -> None:
        delay = PUSH_RECONNECT_MIN_DELAY
        while True:
            try:
                await self._poll_once()
                delay = PUSH_RECONNECT_MIN_DELAY
            except asyncio.CancelledError:
                raise
            except (ClientError, TimeoutError, ValueError, KeyError) as err:
                _LOGGER.debug("Push request failed: %s", err)
                self._set_connected(False)
                await asyncio.sleep(delay)
                delay = min(delay * 2, PUSH_RECONNECT_MAX_DELAY)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected error in push updates")
                self._set_connected(False)
                await asyncio.sleep(PUSH_RECONNECT_MAX_DELAY)

    async def _poll_once(self) -> None:
        session_id = self._coordinator.api_sessionid
        if not session_id or session_id != self._subscribed_session:
            # Fetching the thermostat list subscribes the session.
            await self._coordinator.async_refresh()
            session_id = self._coordinator.api_sessionid
            if not session_id or not self._coordinator.last_update_success:
                raise ValueError("Could not subscribe, no session")
            self._subscribed_session = session_id
            return

        async with self._session.get(
            NOTIFICATION_URL,
            params={"sessionId": session_id},
            timeout=ClientTimeout(total=PUSH_REQUEST_TIMEOUT),
        ) as resp:
            if resp.status == HTTP_UNAUTHORIZED:
                # Session expired; resubscribe through a refresh.
                self._subscribed_session = None
                self._set_connected(False)
                return
            if resp.status != HTTP_OK:
                raise ValueError(f"Notification request returned {resp.status}")
            data: dict[str, Any] = await resp.json(content_type=None)

        self._set_connected(True)

        # A wait with no change comes back with an empty Thermostat.
        payload = data.get("Thermostat") if isinstance(data, dict) else None
        if not payload:
            return

        try:
            thermostat = Thermostat(payload)
        except (KeyError, TypeError) as err:
            # Unknown payload shape: fall back to a normal refresh.
            _LOGGER.debug("Unexpected push payload (%s): %s", err, payload)
            await self._coordinator.async_request_refresh()
            return

        self._coordinator.async_apply_push(thermostat)
