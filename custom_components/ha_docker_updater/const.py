"""Constants for the HA Docker Updater integration."""

# ── Integration identity ──────────────────────────────────────────────────────
DOMAIN = "ha_docker_updater"
INTEGRATION_NAME = "HA Docker Updater"

# ── Entity display ────────────────────────────────────────────────────────────
# DEVICE_NAME is used as the UpdateEntity title property — shown inside the
# update more-info dialog as the software title line.
DEVICE_NAME = "Home Assistant Core"

# ── Config-entry keys (stored in entry.data / entry.options) ─────────────────
CONF_COMPOSE_DIR = "compose_dir"
CONF_COMPOSE_FILE = "compose_file"
CONF_HA_SERVICE_NAME = "ha_service_name"
CONF_TRIGGER_FILE_PATH = "trigger_file_path"
CONF_PRUNE_IMAGES = "prune_images"
CONF_SCAN_INTERVAL = "scan_interval"

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_COMPOSE_DIR = "/home/pi/homeassistant"
DEFAULT_COMPOSE_FILE = "docker-compose.yml"
DEFAULT_HA_SERVICE_NAME = "homeassistant"
DEFAULT_TRIGGER_FILE = "/tmp/ha-docker-updater-trigger"   # noqa: S108  (intentional /tmp use)
DEFAULT_PRUNE_IMAGES = True
DEFAULT_SCAN_INTERVAL = 3600  # seconds — poll GitHub once per hour

# ── GitHub API ────────────────────────────────────────────────────────────────
REPO_API_URL = "https://api.github.com/repos/home-assistant/core/releases/latest"
GITHUB_TIMEOUT = 15          # seconds
GITHUB_RATE_LIMIT_HEADER = "X-RateLimit-Remaining"

# ── Trigger file protocol ─────────────────────────────────────────────────────
# The HA component writes this file; the host-side watcher detects and acts on it.
# Content written to the trigger file so the watcher can validate authenticity.
TRIGGER_FILE_MAGIC = "HA_DOCKER_UPDATER_REQUESTED"

# ── Status / state tracking ───────────────────────────────────────────────────
# Keys stored in hass.data[DOMAIN]
DATA_COORDINATOR = "coordinator"

# ── Logging prefix ────────────────────────────────────────────────────────────
LOG_PREFIX = "[ha-docker-updater]"