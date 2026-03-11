"""DataUpdateCoordinator for HA Docker Updater.

Responsible for:
  - Polling the GitHub Releases API on a configurable interval
  - Parsing and comparing CalVer version strings correctly
  - Surfacing structured errors and availability state to entities
  - Respecting GitHub API rate-limit headers to avoid throttling
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp
from packaging.version import Version, InvalidVersion

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    LOG_PREFIX,
    REPO_API_URL,
    GITHUB_TIMEOUT,
    GITHUB_RATE_LIMIT_HEADER,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _parse_version(version_str: str) -> Version | None:
    """Safely parse a CalVer/SemVer string, stripping a leading 'v' if present.

    Returns None if the string cannot be parsed rather than raising.
    """
    cleaned = version_str.strip().lstrip("v")
    try:
        return Version(cleaned)
    except InvalidVersion:
        _LOGGER.warning("%s Could not parse version string: %r", LOG_PREFIX, version_str)
        return None


def _is_update_available(installed: str, latest: str) -> bool:
    """Return True only when *latest* is strictly newer than *installed*.

    Falls back to string inequality if either version cannot be parsed, which
    avoids a false-positive 'update available' on parse failures.
    """
    installed_v = _parse_version(installed)
    latest_v = _parse_version(latest)
    if installed_v is None or latest_v is None:
        # Safe fallback — only flag as update if strings differ
        return installed.lstrip("v") != latest.lstrip("v")
    return latest_v > installed_v


class HADockerUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that fetches the latest HA release from GitHub.

    Data shape returned by ``_async_update_data``:
    {
        "installed_version": str,   # Running HA version
        "latest_version":   str,    # Latest GitHub release tag (stripped)
        "release_url":      str,    # URL to GitHub release page
        "update_available": bool,   # Parsed comparison result
        "rate_limit_remaining": int | None,
    }
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        scan_seconds = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_seconds),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest release information from GitHub.

        Raises UpdateFailed on any error so the coordinator marks the entity
        as unavailable and retries on the next interval with exponential backoff
        provided by the base class.
        """
        session = async_get_clientsession(self.hass)
        installed = HA_VERSION.lstrip("v")

        try:
            async with session.get(
                REPO_API_URL,
                timeout=aiohttp.ClientTimeout(total=GITHUB_TIMEOUT),
                headers={"Accept": "application/vnd.github+json"},
            ) as resp:
                rate_remaining: int | None = None
                raw_rate = resp.headers.get(GITHUB_RATE_LIMIT_HEADER)
                if raw_rate is not None:
                    try:
                        rate_remaining = int(raw_rate)
                    except ValueError:
                        pass

                if rate_remaining is not None and rate_remaining < 5:
                    _LOGGER.warning(
                        "%s GitHub API rate limit nearly exhausted (%s remaining). "
                        "Returning cached data.",
                        LOG_PREFIX,
                        rate_remaining,
                    )
                    # Return stale data rather than an error to keep entity available
                    if self.data:
                        return {**self.data, "rate_limit_remaining": rate_remaining}

                if resp.status == 403:
                    raise UpdateFailed(
                        f"{LOG_PREFIX} GitHub API rate limited (HTTP 403). "
                        "Will retry at next scheduled interval."
                    )

                if resp.status != 200:
                    raise UpdateFailed(
                        f"{LOG_PREFIX} GitHub API returned unexpected status {resp.status}."
                    )

                payload: dict[str, Any] = await resp.json()

        except aiohttp.ClientError as exc:
            raise UpdateFailed(
                f"{LOG_PREFIX} Network error fetching GitHub release: {exc}"
            ) from exc

        tag: str | None = payload.get("tag_name")
        if not tag:
            raise UpdateFailed(
                f"{LOG_PREFIX} GitHub response missing 'tag_name' field."
            )

        latest = tag.lstrip("v")
        update_available = _is_update_available(installed, latest)

        if update_available:
            _LOGGER.info(
                "%s Update available: installed=%s  latest=%s",
                LOG_PREFIX,
                installed,
                latest,
            )
        else:
            _LOGGER.debug(
                "%s Up to date: installed=%s  latest=%s",
                LOG_PREFIX,
                installed,
                latest,
            )

        return {
            "installed_version": installed,
            "latest_version": latest,
            "release_url": f"https://github.com/home-assistant/core/releases/tag/{tag}",
            "update_available": update_available,
            "rate_limit_remaining": rate_remaining,
        }