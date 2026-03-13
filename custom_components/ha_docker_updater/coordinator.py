"""DataUpdateCoordinator for HA Docker Updater.

Responsible for:
  - Polling the GitHub Releases API on a configurable interval
  - Parsing and comparing CalVer version strings correctly
  - Surfacing structured errors and availability state to entities
  - Respecting GitHub API rate-limit headers to avoid throttling
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp

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


def _parse_version(version_str: str) -> tuple[int, ...] | None:
    """Parse a HA CalVer string (e.g. '2026.3.1') into a comparable tuple.

    Strips a leading 'v' if present.  Returns None if parsing fails so callers
    can fall back gracefully rather than raising.
    """
    cleaned = version_str.strip().lstrip("v")
    try:
        return tuple(int(x) for x in cleaned.split("."))
    except ValueError:
        _LOGGER.warning("%s Could not parse version string: %r", LOG_PREFIX, version_str)
        return None


def _is_update_available(installed: str, latest: str) -> bool:
    """Return True only when *latest* is strictly newer than *installed*.

    Uses tuple comparison of integer version parts, which correctly handles
    HA's CalVer scheme (YYYY.M.patch).  Falls back to string inequality on
    parse failure to avoid false positives.
    """
    installed_v = _parse_version(installed)
    latest_v = _parse_version(latest)
    if installed_v is None or latest_v is None:
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
            async with asyncio.timeout(GITHUB_TIMEOUT):
                async with session.get(
                    REPO_API_URL,
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
                        # Return stale data rather than an error to keep entity available.
                        # _from_cache=True is recorded so log readers can tell the
                        # installed_version and latest_version fields may be outdated.
                        if self.data:
                            return {**self.data, "rate_limit_remaining": rate_remaining, "_from_cache": True}

                    if resp.status == 403:
                        raise UpdateFailed(
                            f"{LOG_PREFIX} GitHub API rate limited (HTTP 403). "
                            "Will retry at next scheduled interval."
                        )

                    if resp.status == 404:
                        raise UpdateFailed(
                            f"{LOG_PREFIX} GitHub release endpoint not found (HTTP 404). "
                            "Check REPO_API_URL in const.py."
                        )

                    if resp.status != 200:
                        raise UpdateFailed(
                            f"{LOG_PREFIX} GitHub API returned unexpected status {resp.status}."
                        )

                    payload: dict[str, Any] = await resp.json()

        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
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