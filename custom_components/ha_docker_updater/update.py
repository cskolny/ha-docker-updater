"""Update entity for HA Docker Updater.

This module is intentionally thin — all version-fetching logic lives in
``coordinator.py``.  The entity's sole runtime responsibility is:

  1. Reflecting coordinator state in the HA UI.
  2. On install: writing the trigger file that the host-side watcher detects.
  3. Surfacing meaningful error states rather than silently failing.

Naming / device design
──────────────────────
This integration does NOT register a device.  The HA frontend shows a
"Device created" dialog after *every* config flow that produces a new device
entry — and for UpdateEntity this dialog is especially intrusive.  By omitting
``device_info`` entirely the dialog never appears.

Without a device the naming rules are:
  ``has_entity_name = True``  +  ``name = "Home Assistant Core Update"``
  →  friendly_name  = "Home Assistant Core Update"
  →  entity_id      = update.home_assistant_core_update

The ``title`` property (separate from entity name) is shown inside the update
more-info dialog as the software title line.
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
from homeassistant.util import dt as dt_util

from .const import (
    CONF_TRIGGER_FILE_PATH,
    DATA_COORDINATOR,
    DEFAULT_TRIGGER_FILE,
    DEVICE_NAME,
    DOMAIN,
    LOG_PREFIX,
    TRIGGER_FILE_MAGIC,
)
from .coordinator import HADockerUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

_POST_INSTALL_POLL_DELAY = 120

UPDATE_ENTITY_DESCRIPTION = UpdateEntityDescription(
    key="ha_docker_update",
    name="Home Assistant Core Update",
    icon="mdi:home-assistant",
    translation_key=None,
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
    """Represents the Home Assistant Docker container update state."""

    entity_description = UPDATE_ENTITY_DESCRIPTION
    # has_entity_name=False (default) means name is the full friendly name,
    # not a suffix appended to a device name.
    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: HADockerUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_update"
        self._attr_supported_features = (
            UpdateEntityFeature.INSTALL
            | UpdateEntityFeature.BACKUP
        )
        self._attr_in_progress = False
        self._trigger_path: str = entry.options.get(
            CONF_TRIGGER_FILE_PATH,
            entry.data.get(CONF_TRIGGER_FILE_PATH, DEFAULT_TRIGGER_FILE),
        )

    # ── UpdateEntity property overrides ──────────────────────────────────────

    @property
    def installed_version(self) -> str | None:
        if self.coordinator.data:
            return self.coordinator.data.get("installed_version")
        return None

    @property
    def latest_version(self) -> str | None:
        if self.coordinator.data:
            return self.coordinator.data.get("latest_version")
        return None

    @property
    def release_url(self) -> str | None:
        if self.coordinator.data:
            return self.coordinator.data.get("release_url")
        return None

    @property
    def title(self) -> str | None:
        """Software title shown inside the update more-info dialog."""
        return DEVICE_NAME  # "Home Assistant Core"

    @property
    def release_summary(self) -> str | None:
        """Short summary shown when an update is available."""
        if not self.coordinator.data:
            return None
        if not self.coordinator.data.get("update_available"):
            return None
        latest = self.coordinator.data.get("latest_version")
        if not latest:
            return None
        summary = (
            f"Home Assistant {latest} is available. "
            "See the release notes for details before updating."
        )
        last_backup = self._get_last_backup_summary()
        if last_backup:
            summary += f"\n\n{last_backup}"
        return summary

    def _get_last_backup_summary(self) -> str | None:
        try:
            backup_states = self.hass.states.async_all("backup")
            if not backup_states:
                return None
            latest = max(backup_states, key=lambda s: s.last_changed)
            delta = dt_util.utcnow() - latest.last_changed
            hours = int(delta.total_seconds() // 3600)
            if hours < 1:
                age = "less than 1 hour ago"
            elif hours == 1:
                age = "1 hour ago"
            else:
                age = f"{hours} hours ago"
            return f"Last automatic backup {age}."
        except Exception:  # noqa: BLE001
            return None

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
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
        """Optionally back up, then trigger the host-side watcher to update."""
        self._attr_in_progress = True
        self.async_write_ha_state()

        if backup:
            _LOGGER.info("%s Backup requested — creating backup before update.", LOG_PREFIX)
            try:
                await self.hass.services.async_call("backup", "create", blocking=True)
                _LOGGER.info("%s Backup completed successfully.", LOG_PREFIX)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error("%s Backup failed: %s — aborting update.", LOG_PREFIX, exc)
                self._attr_in_progress = False
                self.async_write_ha_state()
                return

        _LOGGER.info("%s Writing trigger file: %s", LOG_PREFIX, self._trigger_path)
        try:
            await self.hass.async_add_executor_job(
                self._write_trigger_file, self._trigger_path
            )
            _LOGGER.info("%s Trigger file written. Host watcher will perform the update.", LOG_PREFIX)
        except OSError as exc:
            _LOGGER.error("%s Failed to write trigger file %r: %s", LOG_PREFIX, self._trigger_path, exc)
            self._attr_in_progress = False
            self.async_write_ha_state()
            return

        # Schedule a deferred refresh so the entity reflects the new version
        # once HA has restarted.  If the host-side update fails silently (e.g.
        # the watcher isn't running), _attr_in_progress is still cleared after
        # the delay and the entity returns to "Update available" — no spinner
        # gets permanently stuck.  The try/finally guarantees the flag clears
        # even if the coordinator refresh itself raises.
        async def _delayed_refresh() -> None:
            await asyncio.sleep(_POST_INSTALL_POLL_DELAY)
            try:
                await self.coordinator.async_request_refresh()
            finally:
                self._attr_in_progress = False
                self.async_write_ha_state()

        self.hass.async_create_task(_delayed_refresh())

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _write_trigger_file(path: str) -> None:
        """Atomic trigger file write (write-then-rename)."""
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
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass