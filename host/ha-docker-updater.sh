#!/bin/bash
# =============================================================================
# ha-docker-updater.sh
# Host-side script to update the Home Assistant Docker container.
#
# Called by: ha-docker-updater-watcher.service (systemd)
# Never called directly by the HA container.
#
# Usage: ha-docker-updater.sh [--compose-dir DIR] [--compose-file FILE]
#                              [--service NAME] [--log-file PATH]
#                              [--prune] [--no-prune]
#
# All arguments are optional; defaults match the HA Docker Updater component.
# =============================================================================

set -euo pipefail

# ── Defaults (can be overridden by CLI args or environment variables) ─────────
COMPOSE_DIR="${HA_UPDATER_COMPOSE_DIR:-/home/pi/homeassistant}"
COMPOSE_FILE="${HA_UPDATER_COMPOSE_FILE:-docker-compose.yml}"
HA_SERVICE_NAME="${HA_UPDATER_SERVICE_NAME:-homeassistant}"
LOG_FILE="${HA_UPDATER_LOG_FILE:-/home/pi/homeassistant/ha-docker-updater.log}"
PRUNE_IMAGES="${HA_UPDATER_PRUNE:-true}"

# ── Parse CLI arguments ───────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --compose-dir)   COMPOSE_DIR="$2";    shift 2 ;;
        --compose-file)  COMPOSE_FILE="$2";   shift 2 ;;
        --service)       HA_SERVICE_NAME="$2"; shift 2 ;;
        --log-file)      LOG_FILE="$2";        shift 2 ;;
        --prune)         PRUNE_IMAGES="true";  shift ;;
        --no-prune)      PRUNE_IMAGES="false"; shift ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

# ── Logging ───────────────────────────────────────────────────────────────────
_log() {
    local level="$1"
    local message="$2"
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    local entry="${timestamp} - ${level^^} - (ha-docker-updater) - ${message}"
    echo "${entry}"
    # Ensure log directory exists before writing
    mkdir -p "$(dirname "${LOG_FILE}")"
    echo "${entry}" >> "${LOG_FILE}"
}

log_info()  { _log "INFO"  "$1"; }
log_warn()  { _log "WARN"  "$1"; }
log_error() { _log "ERROR" "$1"; echo "ERROR: $1" >&2; }

# ── Pre-flight checks ─────────────────────────────────────────────────────────
log_info "━━━ HA Docker Updater — starting ━━━"
log_info "Compose dir   : ${COMPOSE_DIR}"
log_info "Compose file  : ${COMPOSE_FILE}"
log_info "Service name  : ${HA_SERVICE_NAME}"
log_info "Prune images  : ${PRUNE_IMAGES}"

# Prefer 'docker compose' (v2 plugin) but fall back to 'docker-compose' (v1 standalone)
if docker compose version &>/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker compose"
    log_info "Docker Compose : v2 plugin (docker compose)"
elif command -v docker-compose &>/dev/null; then
    DOCKER_COMPOSE_CMD="docker-compose"
    log_info "Docker Compose : v1 standalone (docker-compose)"
else
    log_error "Neither 'docker compose' nor 'docker-compose' found. Aborting."
    exit 1
fi

if [[ ! -d "${COMPOSE_DIR}" ]]; then
    log_error "Compose directory not found: ${COMPOSE_DIR}"
    exit 1
fi

COMPOSE_PATH="${COMPOSE_DIR}/${COMPOSE_FILE}"
if [[ ! -f "${COMPOSE_PATH}" ]]; then
    log_error "Compose file not found: ${COMPOSE_PATH}"
    exit 1
fi

# Confirm Docker daemon is reachable
if ! docker info &>/dev/null; then
    log_error "Cannot connect to Docker daemon. Is Docker running?"
    exit 1
fi

# ── Step 1: Pull the latest image ─────────────────────────────────────────────
log_info "Step 1/3 — Pulling latest image for service '${HA_SERVICE_NAME}'..."
cd "${COMPOSE_DIR}"

if ! ${DOCKER_COMPOSE_CMD} -f "${COMPOSE_FILE}" pull "${HA_SERVICE_NAME}"; then
    log_error "docker compose pull failed. Check network and Docker Hub status."
    exit 1
fi
log_info "Image pull completed successfully."

# ── Step 2: Recreate the container ───────────────────────────────────────────
log_info "Step 2/3 — Recreating container for service '${HA_SERVICE_NAME}'..."
# --force-recreate  : rebuild even if config is unchanged (use new image)
# --remove-orphans  : clean up containers for removed services
if ! ${DOCKER_COMPOSE_CMD} -f "${COMPOSE_FILE}" up -d \
        --force-recreate \
        --remove-orphans \
        "${HA_SERVICE_NAME}"; then
    log_error "docker compose up failed. Review 'docker compose logs ${HA_SERVICE_NAME}'."
    exit 1
fi
log_info "Container recreated and started successfully."

# ── Step 3: Prune unused images (optional) ────────────────────────────────────
if [[ "${PRUNE_IMAGES}" == "true" ]]; then
    log_info "Step 3/3 — Pruning unused Docker images..."
    if docker image prune -af >> "${LOG_FILE}" 2>&1; then
        log_info "Image prune completed."
    else
        log_warn "Image prune returned a non-zero exit code (non-fatal)."
    fi
else
    log_info "Step 3/3 — Image prune skipped (disabled in config)."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
log_info "━━━ HA Docker Updater — finished successfully ━━━"
exit 0