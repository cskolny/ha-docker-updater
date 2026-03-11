"""Update entity for HA Docker Updater.

This module is intentionally thin — all version-fetching logic lives in
``coordinator.py``.  The entity's sole runtime responsibility is:

  1. Reflecting coordinator state in the HA UI.
  2. On install: writing the trigger file that the host-side watcher detects.
  3. Surfacing meaningful error states rather than silently failing.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_TRIGGER_FILE_PATH,
    DATA_COORDINATOR,
    DEFAULT_TRIGGER_FILE,
    DOMAIN,
    LOG_PREFIX,
    TRIGGER_FILE_MAGIC,
)
from .coordinator import HADockerUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# ── Update interval after a successful install trigger (seconds) ──────────────
_POST_INSTALL_POLL_DELAY = 60

UPDATE_ENTITY_DESCRIPTION = UpdateEntityDescription(
    key="ha_docker_update",
    name="HA Docker Update",
    icon="mdi:docker",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the update entity from a config entry."""
    coordinator: HADockerUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([HADockerUpdateEntity(coordinator, entry)])


class HADockerUpdateEntity(CoordinatorEntity[HADockerUpdateCoordinator], UpdateEntity):
    """Represents the Home Assistant Docker container update state.

    Inheriting from ``CoordinatorEntity`` means HA automatically:
      - Calls ``coordinator.async_request_refresh()`` on the configured interval.
      - Marks the entity unavailable when the coordinator raises ``UpdateFailed``.
      - Handles state writes after each successful coordinator refresh.
    """

    entity_description = UPDATE_ENTITY_DESCRIPTION

    def __init__(
        self,
        coordinator: HADockerUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_update"
        self._attr_has_entity_name = True
        self._attr_supported_features = UpdateEntityFeature.INSTALL
        self._attr_in_progress = False
        self._trigger_path: str = entry.options.get(
            CONF_TRIGGER_FILE_PATH,
            entry.data.get(CONF_TRIGGER_FILE_PATH, DEFAULT_TRIGGER_FILE),
        )

    # ── UpdateEntity property overrides ──────────────────────────────────────

    @property
    def installed_version(self) -> str | None:
        """Currently running HA version."""
        if self.coordinator.data:
            return self.coordinator.data.get("installed_version")
        return None

    @property
    def latest_version(self) -> str | None:
        """Latest available HA version from GitHub."""
        if self.coordinator.data:
            return self.coordinator.data.get("latest_version")
        return None

    @property
    def release_url(self) -> str | None:
        """Direct link to the GitHub release notes."""
        if self.coordinator.data:
            return self.coordinator.data.get("release_url")
        return None

    @property
    def available(self) -> bool:
        """Mark entity unavailable when coordinator has never succeeded."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose diagnostic attributes visible in Developer Tools → States."""
        attrs: dict[str, Any] = {}
        if self.coordinator.data:
            rate = self.coordinator.data.get("rate_limit_remaining")
            if rate is not None:
                attrs["github_rate_limit_remaining"] = rate
        attrs["trigger_file_path"] = self._trigger_path
        return attrs

    # ── Install action ────────────────────────────────────────────────────────

    async def async_install(
        self,
        version: str | None,
        backup: bool,
        **kwargs: Any,
    ) -> None:
        """Trigger the host-side watcher to perform the Docker update.

        The HA container cannot restart itself via docker-compose — doing so
        would kill the process mid-execution.  Instead we write a trigger file
        to a path that is volume-mounted on the host.  A lightweight systemd
        service (``ha-docker-update-watcher.service``) running on the host
        detects the file, runs the update, and removes the trigger.

        The trigger file contains a magic string so the watcher can perform a
        basic authenticity check before acting.
        """
        _LOGGER.info(
            "%s Install requested. Writing trigger file: %s",
            LOG_PREFIX,
            self._trigger_path,
        )

        self._attr_in_progress = True
        self.async_write_ha_state()

        try:
            await self.hass.async_add_executor_job(
                self._write_trigger_file, self._trigger_path
            )
            _LOGGER.info(
                "%s Trigger file written successfully. "
                "Host-side watcher will perform the update.",
                LOG_PREFIX,
            )
        except OSError as exc:
            _LOGGER.error(
                "%s Failed to write trigger file %r: %s",
                LOG_PREFIX,
                self._trigger_path,
                exc,
            )
            self._attr_in_progress = False
            self.async_write_ha_state()
            return

        # Schedule a coordinator refresh after the container likely restarts.
        # This gives the watcher ~60 s to act before we poll again.
        async def _delayed_refresh() -> None:
            await asyncio.sleep(_POST_INSTALL_POLL_DELAY)
            await self.coordinator.async_request_refresh()
            self._attr_in_progress = False
            self.async_write_ha_state()

        self.hass.async_create_task(_delayed_refresh())

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _write_trigger_file(path: str) -> None:
        """Write the trigger file.  Runs in executor (blocking I/O).

        Uses an atomic write pattern (write-then-rename) so the watcher never
        sees a partially-written file.
        """
        trigger_dir = os.path.dirname(path)
        if trigger_dir and not os.path.isdir(trigger_dir):
            raise OSError(
                f"Trigger file directory does not exist: {trigger_dir!r}. "
                "Ensure the path is volume-mounted from the host."
            )

        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                fh.write(TRIGGER_FILE_MAGIC + "\n")
            os.replace(tmp_path, path)  # Atomic on POSIX
        finally:
            # Clean up temp file if rename failed
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass