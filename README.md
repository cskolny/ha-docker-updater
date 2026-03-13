# HA Docker Updater

A production-grade Home Assistant custom component that enables one-click updates of your Home Assistant Docker container directly from the HA UI — without SSH, without manual docker-compose commands, and without ever leaving Home Assistant.

---

## Architecture

This integration uses a **two-part design** to safely update a running Docker container — something a container cannot do to itself.

```
┌─────────────────────────────────────────────────────────────────┐
│  Raspberry Pi / Docker Host                                     │
│                                                                 │
│  ┌─────────────────────────────────┐                           │
│  │  HA Container                   │                           │
│  │                                 │                           │
│  │  coordinator.py                 │   GitHub API              │
│  │    └─ polls GitHub releases ────┼──────────────────────►   │
│  │                                 │                           │
│  │  update.py (UpdateEntity)       │                           │
│  │    └─ on Install: writes ───────┼──┐                       │
│  │       trigger file              │  │  volume mount         │
│  └─────────────────────────────────┘  │                       │
│                                       ▼                        │
│  /tmp/ha-docker-updater-trigger  ◄─────┘                       │
│           │                                                     │
│           │  (inotify poll every 5s)                           │
│           ▼                                                     │
│  ha-docker-updater-watcher.sh (systemd service)                 │
│    1. Validates magic string                                    │
│    2. Removes trigger file                                      │
│    3. Acquires lock                                             │
│    4. Calls ha-docker-updater.sh                               │
│         └─ docker compose pull homeassistant                   │
│         └─ docker compose up -d --force-recreate               │
│         └─ docker image prune -af  (optional)                  │
└─────────────────────────────────────────────────────────────────┘
```

### Why two parts?

When `docker compose up --force-recreate` runs, it **stops and replaces the running container**. Any script running *inside* that container is killed mid-execution — the update can never complete. The host-side watcher runs outside the container and is unaffected by the container restart.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Home Assistant in Docker | Installed via `docker-compose` or `docker compose` |
| Docker Compose v1 or v2 | Both supported; v2 preferred |
| Raspberry Pi OS / Debian / Ubuntu | Any systemd-based Linux host |
| Python `packaging` library | Installed automatically by HA from `manifest.json` |

---

## Installation

### Part 1 — HA Custom Component

1. Copy the `custom_components/ha_docker_updater/` folder into your HA `config/custom_components/` directory:
   ```
   config/
   └── custom_components/
       └── ha_docker_updater/
           ├── __init__.py
           ├── coordinator.py
           ├── update.py
           ├── config_flow.py
           ├── const.py
           ├── manifest.json
           ├── strings.json
           └── translations/
               └── en.json
   ```

2. Add a volume mount to your `docker-compose.yml` so the trigger file path is shared between the container and the host:
   ```yaml
   services:
     homeassistant:
       image: ghcr.io/home-assistant/home-assistant:stable
       volumes:
         - ./config:/config
         - /tmp:/tmp          # ← Shares /tmp with the host for the trigger file
         - /etc/localtime:/etc/localtime:ro
   ```
   > **Security note:** Mounting `/tmp` is the simplest option. For a more restrictive setup, create a dedicated directory (e.g., `/home/pi/ha_ipc`) and mount that instead, then set your trigger file path accordingly.

3. Restart Home Assistant.

4. In HA: **Settings → Devices & Services → Add Integration → HA Docker Updater**

5. Fill in the setup form:
   - **Docker Compose directory**: `/home/pi/homeassistant`
   - **Compose filename**: `docker-compose.yml`
   - **HA service name**: `homeassistant`
   - **Trigger file path**: `/tmp/ha-docker-updater-trigger`
   - **Prune images**: Enabled (recommended)
   - **Scan interval**: `3600` (1 hour)

---

### Part 2 — Host-side Watcher (systemd service)

Run these commands on your **Raspberry Pi / Docker host** (not inside the container):

```bash
# 1. Copy scripts to system bin
sudo cp host/ha-docker-updater.sh         /usr/local/bin/
sudo cp host/ha-docker-updater-watcher.sh  /usr/local/bin/
sudo chmod +x /usr/local/bin/ha-docker-updater.sh
sudo chmod +x /usr/local/bin/ha-docker-updater-watcher.sh

# 2. Install the systemd unit
sudo cp host/ha-docker-updater-watcher.service /etc/systemd/system/

# 3. Edit the service file to match your username and paths
sudo nano /etc/systemd/system/ha-docker-updater-watcher.service

# 4. Enable and start
sudo systemctl daemon-reload
sudo systemctl enable ha-docker-updater-watcher.service
sudo systemctl start  ha-docker-updater-watcher.service

# 5. Verify
sudo systemctl status ha-docker-updater-watcher.service
journalctl -u ha-docker-updater-watcher.service -f
```

---

## Usage

Once both parts are installed, a new **HA Docker Update** entity appears in your update dashboard (`Settings → System → Updates`).

| State | Meaning |
|---|---|
| **Up to date** | Installed version matches latest GitHub release |
| **Update available** | A newer version is available — click **Install** |
| **Updating** | Trigger file has been written; watcher is running |
| **Unavailable** | GitHub API unreachable; will retry next interval |

### Automations

You can automate updates using standard HA update entity triggers:

```yaml
automation:
  alias: "Auto-update HA Docker when update available"
  trigger:
    - platform: state
      entity_id: update.ha_docker_update
      to: "on"
  action:
    - service: update.install
      target:
        entity_id: update.ha_docker_update
```

---

## Configuration Options

All options are adjustable post-setup via **Settings → Devices & Services → HA Docker Updater → Configure**:

| Option | Default | Description |
|---|---|---|
| `compose_dir` | `/home/pi/homeassistant` | Host-side directory with your `docker-compose.yml` |
| `compose_file` | `docker-compose.yml` | Compose filename |
| `ha_service_name` | `homeassistant` | Service name in the Compose file |
| `trigger_file_path` | `/tmp/ha-docker-updater-trigger` | File written by HA to signal an update |
| `prune_images` | `true` | Remove old Docker images after update |
| `scan_interval` | `3600` | Seconds between GitHub version checks (300–86400) |

---

## Log Files

| Location | Contents |
|---|---|
| HA logs (`Settings → System → Logs`) | Coordinator fetch results, trigger write status |
| `/home/pi/homeassistant/ha-docker-updater.log` | Host-side watcher and updater script output |
| `journalctl -u ha-docker-updater-watcher` | systemd service lifecycle events |

---

## Security Considerations

- The trigger file uses a **magic string** (`HA_DOCKER_UPDATER_REQUESTED`) that the watcher validates before acting. Stray or empty files are silently ignored.
- A **lock file** prevents concurrent update runs.
- The trigger file is **deleted immediately** after validation so a watcher restart cannot re-trigger an update.
- The systemd service runs as **your user** (not root). Ensure your user is in the `docker` group: `sudo usermod -aG docker pi`.
- For tighter security, replace the shared `/tmp` mount with a dedicated directory owned by your HA user.

---

## Troubleshooting

**Update entity shows "Unavailable"**
- Check HA logs for GitHub API errors.
- Verify your Pi has outbound HTTPS access to `api.github.com`.

**Trigger file is written but nothing happens**
- Confirm the watcher service is running: `sudo systemctl status ha-docker-updater-watcher`
- Confirm `/tmp` (or your custom path) is volume-mounted in `docker-compose.yml`.
- Check the updater log: `tail -f /home/pi/homeassistant/ha-docker-updater.log`

**"Trigger file directory does not exist" error in HA setup**
- The path you entered is not accessible inside the container.
- Verify the volume mount in `docker-compose.yml` and restart HA.

**docker compose pull fails**
- Check network connectivity from the host.
- Run `docker compose pull homeassistant` manually to see the error.

---

## Complementary Projects

This integration is designed to complement the **Green Button Import** custom component, sharing the same code style, logging conventions, coordinator pattern, and config-flow structure. Both components can be managed together in your HA instance.

---

## License

MIT — see LICENSE file.