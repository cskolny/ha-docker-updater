# HA Docker Updater — Home Assistant Custom Integration

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.12%2B-blue?logo=homeassistant)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![Release](https://img.shields.io/github/v/release/cskolny/ha-docker-updater)](https://github.com/cskolny/ha-docker-updater/releases)

Update your **Home Assistant Docker container** directly from the HA UI — no SSH, no terminal, no manual `docker compose` commands. A new update entity appears in **Settings → System → Updates** alongside HA's own built-in update cards.

---

## How It Works

A container cannot restart itself — any script running inside the container is killed the moment `docker compose up --force-recreate` replaces it. This integration solves that fundamental problem with a **two-part design**:

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
│           │  (poll every 5s)                                   │
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

**Part 1 — HA custom component** (runs inside the container): polls GitHub for the latest HA release, compares it against the running version, and writes a trigger file to a volume-mounted path when you click **Install**.

**Part 2 — Host-side watcher** (runs as a systemd service on the Docker host): monitors the trigger file, validates it, then runs `docker compose pull` and `docker compose up -d --force-recreate` — safely outside the container.

---

## Features

- 🔄 **One-click updates** from Settings → System → Updates
- 💾 **Optional automatic backup** before each update
- 🔍 **GitHub release polling** with configurable interval (5 min – 24 hr)
- 🛡️ **GitHub API rate-limit awareness** — returns cached data instead of erroring when the limit is nearly exhausted
- ⚡ **Atomic trigger file writes** — write-then-rename so the watcher never sees a partial file
- 🔒 **Magic string validation** — the watcher ignores stray or empty files
- 🔐 **Lock file** prevents concurrent update runs
- 🐳 **Docker Compose v1 and v2** both supported; v2 preferred
- 🗑️ **Optional image pruning** after a successful update to reclaim disk space
- ⚙️ **Full config flow** — set up entirely from the UI, no `configuration.yaml` changes
- 🔧 **Options flow** — adjust all settings post-setup without re-adding the integration
- 📋 **Structured timestamped logging** on both the HA component and host-side scripts
- 🚀 **`deploy.sh`** — one-command deployment to your Raspberry Pi

---

## Requirements

- Home Assistant running in Docker (via `docker-compose` or `docker compose`)
- Docker Compose v1 or v2 (v2 preferred)
- A systemd-based Linux host (Raspberry Pi OS, Debian, Ubuntu)
- Home Assistant **2025.12 or later**

---

## Installation

### Part 1 — HA Custom Component

**Manual:**

1. Copy the `custom_components/ha_docker_updater/` folder into your HA config directory:
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
   > **Security note:** Mounting `/tmp` is the simplest option. For a more restrictive setup, create a dedicated directory (e.g., `/home/pi/ha_ipc`) and mount that instead, then set your trigger file path accordingly in the HA setup form.

3. Restart Home Assistant.

4. Go to **Settings → Devices & Services → Add Integration → HA Docker Updater**

5. Fill in the setup form:

   | Field | Default | Description |
   |---|---|---|
   | Docker Compose directory | `/home/pi/homeassistant` | Host-side path to your Compose project |
   | Compose filename | `docker-compose.yml` | Filename of your Compose file |
   | HA service name | `homeassistant` | Service name in the Compose file |
   | Trigger file path | `/tmp/ha-docker-updater-trigger` | Must be inside a volume-mounted directory |
   | Prune images | Enabled | Removes old images after update |
   | Scan interval | `3600` | Seconds between GitHub version checks |

**HACS (Custom repository):**

1. In HACS → Integrations → three-dot menu → **Custom repositories**
2. Add `https://github.com/cskolny/ha-docker-updater` with category **Integration**
3. Search for "HA Docker Updater" and install

---

### Part 2 — Host-side Watcher (systemd service)

Run these commands on your **Raspberry Pi / Docker host** — not inside the container:

```bash
# 1. Copy scripts to system bin
sudo cp host/ha-docker-updater.sh          /usr/local/bin/
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

> **Tip:** The `deploy.sh` script in the repository automates both parts — it rsyncs the HA component to your Pi and installs the host scripts and systemd service in one command. Run `./deploy.sh --help` for options.

---

## Usage

Once both parts are installed, a **Home Assistant Core Update** entity appears in **Settings → System → Updates**.

| State | Meaning |
|---|---|
| **Up to date** | Installed version matches the latest GitHub release |
| **Update available** | A newer version is available — click **Install** |
| **Installing** | Trigger file written; host watcher is running the update |
| **Unavailable** | GitHub API unreachable; will retry at the next interval |

### Automations

You can automate updates using standard HA update entity triggers:

```yaml
automation:
  alias: "Auto-update HA Docker when update available"
  trigger:
    - platform: state
      entity_id: update.home_assistant_core_update
      to: "on"
  action:
    - action: update.install
      target:
        entity_id: update.home_assistant_core_update
```

---

## Configuration Options

All options are adjustable post-setup via **Settings → Devices & Services → HA Docker Updater → Configure**:

| Option | Default | Description |
|---|---|---|
| `compose_dir` | `/home/pi/homeassistant` | Host-side directory containing your `docker-compose.yml` |
| `compose_file` | `docker-compose.yml` | Compose filename |
| `ha_service_name` | `homeassistant` | Service name for Home Assistant in the Compose file |
| `trigger_file_path` | `/tmp/ha-docker-updater-trigger` | Path written by HA to signal an update; must be volume-mounted |
| `prune_images` | `true` | Run `docker image prune -af` after a successful update |
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
- The trigger file is **deleted immediately** after validation, so a watcher restart cannot re-trigger an update.
- The systemd service runs as **your user** (not root). Ensure your user is in the `docker` group:
  ```bash
  sudo usermod -aG docker pi
  ```
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
- The path you entered is not accessible from inside the container.
- Verify the volume mount in `docker-compose.yml` and restart HA.

**`docker compose pull` fails**
- Check network connectivity from the host.
- Run `docker compose pull homeassistant` manually to see the full error output.

**Watcher service fails to start**
- Check `journalctl -u ha-docker-updater-watcher -n 50` for errors.
- Confirm the scripts are executable: `ls -la /usr/local/bin/ha-docker-updater*.sh`
- Confirm your user is in the `docker` group: `groups pi`

---

## Complementary Projects

This integration is designed to complement the **[Green Button Energy Import](https://github.com/cskolny/ha-green-button-energy)** custom component, sharing the same code style, logging conventions, coordinator pattern, and config-flow structure. Both components can be managed together in your HA instance.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
