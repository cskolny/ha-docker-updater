# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-03-11

### Changed
- **`packaging` dependency removed** — version comparison now uses a stdlib
  `tuple(int, ...)` split on `"."`, which handles HA's CalVer scheme
  (`YYYY.M.patch`) correctly with no external dependencies, simplifying
  installation and removing a pip requirement that was unnecessary.
- **`async_timeout` replaced with `asyncio.timeout`** — the third-party
  `async-timeout` package is forbidden in HA 2025.7+. All GitHub API calls now
  use the stdlib `asyncio.timeout()` context manager (Python 3.11+), which is
  the pattern required by current HA core.
- **`asyncio.TimeoutError` added to exception handler** — when using
  `asyncio.timeout()`, timeouts raise `asyncio.TimeoutError` rather than
  `aiohttp.ClientError`. Both are now caught and wrapped in `UpdateFailed` so
  a GitHub timeout surfaces as a clean entity-unavailable state rather than an
  unhandled exception in the HA event loop.
- **`FlowResult` replaced with `ConfigFlowResult`** — `FlowResult` from
  `homeassistant.data_entry_flow` was deprecated in HA 2024.4 and removed in
  HA 2025.9. All config flow and options flow return types now use
  `ConfigFlowResult` from `homeassistant.config_entries`, which is the correct
  import for HA 2025.9+.
- **`OptionsFlow.__init__` removed** — explicitly storing `self._config_entry`
  in `OptionsFlow.__init__` was deprecated in HA 2024.11 and broke hard in
  HA 2025.12. The options flow now uses `self.config_entry` provided by the
  base class, which is the only supported pattern going forward.
- **`manifest.json` minimum HA version set to `2025.12.0`** — reflects the
  `OptionsFlow` base class requirement and `ConfigFlowResult` availability.
  Earlier versions are not supported.
- **`hacs.json` added** — enables future HACS submission with correct domain
  (`update`), `iot_class` (`cloud_polling`), and minimum HA version.

## [1.0.0] - 2026-03-10

### Added
- Initial release.
- **`UpdateEntity` integration** — appears in **Settings → System → Updates**
  alongside other HA update entities. Supports the Install action from the
  standard HA update card.
- **GitHub release polling** via `DataUpdateCoordinator` — queries the GitHub
  Releases API on a configurable interval (default 1 hour) and compares the
  latest tag against the running HA version using CalVer tuple comparison.
- **Two-part update architecture** — the HA component writes a trigger file to
  a volume-mounted path; a host-side systemd watcher service detects the file
  and executes `docker compose pull` + `up --force-recreate`. This correctly
  solves the fundamental problem that a container cannot restart itself.
- **Atomic trigger file writes** — uses write-then-rename (`os.replace`) so the
  host watcher never sees a partially-written file.
- **Magic string validation** — the trigger file contains `HA_DOCKER_UPDATER_REQUESTED`;
  the watcher validates this before acting to prevent stray files from triggering
  unintended updates.
- **Lock file** on the host watcher prevents concurrent update runs.
- **Config flow** — full guided UI setup via **Settings → Devices & Services →
  Add Integration**. No `configuration.yaml` changes required.
- **Options flow** — all settings adjustable post-setup without removing and
  re-adding the integration.
- **Trigger directory validation** in config and options flow — detects missing
  volume mounts before the integration is saved, surfacing a clear error rather
  than a silent runtime failure.
- **GitHub API rate-limit awareness** — reads `X-RateLimit-Remaining` header;
  returns cached data instead of erroring when the limit is nearly exhausted.
- **`docker compose` v1 / v2 detection** — host-side update script automatically
  prefers the v2 plugin (`docker compose`) and falls back to the v1 standalone
  binary (`docker-compose`).
- **Optional image pruning** — configurable `prune_images` option runs
  `docker image prune -af` after a successful update to reclaim disk space.
- **Structured timestamped logging** on both the HA component and the host-side
  scripts, written to `ha-docker-updater.log` in the Compose directory.
- **systemd service** (`ha-docker-updater-watcher.service`) with resource limits,
  correct Docker socket dependencies, and `Restart=on-failure`.
- **`deploy.sh`** — one-command deployment script (modelled on the Green Button
  Energy Import project) supporting `--skip-restart`, `--component-only`, and
  `--host-only` flags.
