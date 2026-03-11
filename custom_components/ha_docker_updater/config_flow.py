"""Config flow and options flow for HA Docker Updater.

Setup flow
──────────
Step 1 (user)  — collect compose directory, compose filename, service name,
                 trigger file path, image prune preference, and poll interval.
Step 2          — validate that the trigger-file *directory* is accessible from
                 inside the container (it must be a volume mount).

Options flow
────────────
Exposes the same fields post-setup so the user can adjust them without
removing and re-adding the integration.
"""

from __future__ import annotations

import os
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback

from .const import (
    CONF_COMPOSE_DIR,
    CONF_COMPOSE_FILE,
    CONF_HA_SERVICE_NAME,
    CONF_PRUNE_IMAGES,
    CONF_SCAN_INTERVAL,
    CONF_TRIGGER_FILE_PATH,
    DEFAULT_COMPOSE_DIR,
    DEFAULT_COMPOSE_FILE,
    DEFAULT_HA_SERVICE_NAME,
    DEFAULT_PRUNE_IMAGES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TRIGGER_FILE,
    DOMAIN,
    INTEGRATION_NAME,
    LOG_PREFIX,
)

_LOGGER = logging.getLogger(__name__)

# ── Validation helpers ────────────────────────────────────────────────────────

def _validate_trigger_dir(trigger_path: str) -> str | None:
    """Return an error key if the trigger file's parent directory is unusable.

    We can only validate that the *directory* exists from inside the container.
    A missing directory almost always means the volume mount is not configured.
    """
    parent = os.path.dirname(trigger_path) or "/"
    if not os.path.isdir(parent):
        return "trigger_dir_not_found"
    if not os.access(parent, os.W_OK):
        return "trigger_dir_not_writable"
    return None


def _build_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build a voluptuous schema pre-populated with *defaults*."""
    return vol.Schema(
        {
            vol.Required(
                CONF_COMPOSE_DIR,
                default=defaults.get(CONF_COMPOSE_DIR, DEFAULT_COMPOSE_DIR),
            ): str,
            vol.Required(
                CONF_COMPOSE_FILE,
                default=defaults.get(CONF_COMPOSE_FILE, DEFAULT_COMPOSE_FILE),
            ): str,
            vol.Required(
                CONF_HA_SERVICE_NAME,
                default=defaults.get(CONF_HA_SERVICE_NAME, DEFAULT_HA_SERVICE_NAME),
            ): str,
            vol.Required(
                CONF_TRIGGER_FILE_PATH,
                default=defaults.get(CONF_TRIGGER_FILE_PATH, DEFAULT_TRIGGER_FILE),
            ): str,
            vol.Required(
                CONF_PRUNE_IMAGES,
                default=defaults.get(CONF_PRUNE_IMAGES, DEFAULT_PRUNE_IMAGES),
            ): bool,
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(int, vol.Range(min=300, max=86400)),
        }
    )


# ── Config flow ───────────────────────────────────────────────────────────────

class HADockerUpdaterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Display and process the user setup form."""
        # Prevent duplicate entries
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}

        if user_input is not None:
            trigger_error = await self.hass.async_add_executor_job(
                _validate_trigger_dir, user_input[CONF_TRIGGER_FILE_PATH]
            )
            if trigger_error:
                errors[CONF_TRIGGER_FILE_PATH] = trigger_error
            else:
                _LOGGER.info(
                    "%s Config flow completed. Trigger path: %s",
                    LOG_PREFIX,
                    user_input[CONF_TRIGGER_FILE_PATH],
                )
                return self.async_create_entry(
                    title=INTEGRATION_NAME,
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(user_input or {}),
            errors=errors,
            description_placeholders={
                "default_trigger": DEFAULT_TRIGGER_FILE,
                "docs_url": "https://github.com/cskolny/ha-docker-updater#volume-mount-setup",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HADockerUpdaterOptionsFlow:
        """Return the options flow handler."""
        return HADockerUpdaterOptionsFlow(config_entry)


# ── Options flow ──────────────────────────────────────────────────────────────

class HADockerUpdaterOptionsFlow(config_entries.OptionsFlow):
    """Allow the user to adjust settings after initial setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Display and process the options form."""
        errors: dict[str, str] = {}

        # Merge current options on top of original data so all fields populate.
        # self.config_entry is provided by the OptionsFlow base class — do NOT
        # store it manually in __init__ as that is deprecated since HA 2025.12.
        current = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            trigger_error = await self.hass.async_add_executor_job(
                _validate_trigger_dir, user_input[CONF_TRIGGER_FILE_PATH]
            )
            if trigger_error:
                errors[CONF_TRIGGER_FILE_PATH] = trigger_error
            else:
                return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(user_input or current),
            errors=errors,
        )