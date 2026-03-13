#!/bin/bash
# =============================================================================
# ha-docker-updater-watcher.sh
# Host-side daemon loop — watches for the trigger file written by the HA
# Docker Updater custom component, then calls ha-docker-updater.sh.
#
# Designed to be run as a systemd service (see ha-docker-updater-watcher.service).
# Should NOT be called manually in normal operation.
#
# Security model
# ──────────────
#  1. The trigger file must contain the magic string defined in the HA component
#     (TRIGGER_FILE_MAGIC = "HA_DOCKER_UPDATER_REQUESTED") to prevent accidental
#     or unauthorised triggers from stray files.
#  2. Only one update can run at a time; a lock file prevents concurrent runs.
#  3. The trigger file is removed immediately after it is validated so a
#     crashed watcher restart doesn't re-trigger.
# =============================================================================

set -euo pipefail

# ── Configuration (override via environment or edit here) ─────────────────────
TRIGGER_FILE="${HA_UPDATER_TRIGGER_FILE:-/tmp/ha-docker-updater-trigger}"
UPDATER_SCRIPT="${HA_UPDATER_SCRIPT:-/usr/local/bin/ha-docker-updater.sh}"
LOG_FILE="${HA_UPDATER_LOG_FILE:-/home/pi/homeassistant/ha-docker-updater.log}"
LOCK_FILE="${HA_UPDATER_LOCK_FILE:-/tmp/ha-docker-updater.lock}"
POLL_INTERVAL="${HA_UPDATER_POLL_INTERVAL:-5}"   # seconds between trigger checks
MAGIC_STRING="HA_DOCKER_UPDATER_REQUESTED"

# ── Logging ───────────────────────────────────────────────────────────────────
_log() {
    local level="$1"
    local message="$2"
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    local entry="${timestamp} - ${level^^} - (ha-update-watcher) - ${message}"
    echo "${entry}"
    mkdir -p "$(dirname "${LOG_FILE}")"
    echo "${entry}" >> "${LOG_FILE}"
}

log_info()  { _log "INFO"  "$1"; }
log_warn()  { _log "WARN"  "$1"; }
log_error() { _log "ERROR" "$1"; echo "ERROR: $1" >&2; }

# ── Startup ───────────────────────────────────────────────────────────────────
log_info "━━━ HA Docker Update Watcher starting ━━━"
log_info "Trigger file  : ${TRIGGER_FILE}"
log_info "Updater script: ${UPDATER_SCRIPT}"
log_info "Poll interval : ${POLL_INTERVAL}s"

if [[ ! -x "${UPDATER_SCRIPT}" ]]; then
    log_error "Updater script not found or not executable: ${UPDATER_SCRIPT}"
    exit 1
fi

# ── Cleanup handler ───────────────────────────────────────────────────────────
cleanup() {
    log_info "Watcher shutting down — cleaning up."
    rm -f "${LOCK_FILE}"
}
trap cleanup EXIT INT TERM

# ── Main loop ─────────────────────────────────────────────────────────────────
while true; do
    if [[ -f "${TRIGGER_FILE}" ]]; then
        log_info "Trigger file detected: ${TRIGGER_FILE}"

        # Validate magic string
        file_content="$(cat "${TRIGGER_FILE}" 2>/dev/null || true)"
        if [[ "${file_content}" != *"${MAGIC_STRING}"* ]]; then
            log_warn "Trigger file content invalid (magic string mismatch). Ignoring."
            rm -f "${TRIGGER_FILE}"
            sleep "${POLL_INTERVAL}"
            continue
        fi

        # Remove trigger immediately to prevent re-triggering after a restart
        rm -f "${TRIGGER_FILE}"
        log_info "Trigger file removed. Proceeding with update."

        # Enforce single-run lock — validate the PID is still alive so a
        # crashed watcher or SIGKILL'd updater doesn't leave a permanent block.
        if [[ -f "${LOCK_FILE}" ]]; then
            lock_pid="$(cat "${LOCK_FILE}" 2>/dev/null || echo "")"
            if [[ -n "${lock_pid}" ]] && kill -0 "${lock_pid}" 2>/dev/null; then
                log_warn "Update already in progress (PID ${lock_pid} is running). Skipping."
                sleep "${POLL_INTERVAL}"
                continue
            else
                log_warn "Stale lock file found (PID '${lock_pid}' is not running). Removing and proceeding."
                rm -f "${LOCK_FILE}"
            fi
        fi

        # Acquire lock
        echo $$ > "${LOCK_FILE}"

        log_info "Invoking updater script: ${UPDATER_SCRIPT}"
        if "${UPDATER_SCRIPT}"; then
            log_info "Update completed successfully."
        else
            exit_code=$?
            log_error "Updater script exited with code ${exit_code}. See log for details."
        fi

        # Release lock
        rm -f "${LOCK_FILE}"
    fi

    sleep "${POLL_INTERVAL}"
done