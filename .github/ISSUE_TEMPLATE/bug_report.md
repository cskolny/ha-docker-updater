---
name: Bug report
about: Something isn't working correctly
title: "[BUG] "
labels: bug
assignees: cskolny
---

## Describe the bug
A clear description of what went wrong.

## Steps to reproduce
1. Go to '...'
2. Click '...'
3. See error

## Expected behavior
What you expected to happen.

## Actual behavior
What actually happened. Include any error messages shown in HA notifications or the integration page.

## HA log output
Paste relevant log lines from **Settings → System → Logs** (filter for `ha_docker_updater`):

```
paste log output here
```

## Host log output
Paste relevant lines from the host-side updater log (if the issue is with the update process itself):

```bash
tail -50 /home/pi/homeassistant/ha-docker-updater.log
```

```
paste log output here
```

## Watcher service status
Paste the output of the following command from your Raspberry Pi:

```bash
sudo systemctl status ha-docker-update-watcher.service
```

```
paste output here
```

> **Do not include sensitive information** such as API tokens, passwords, or private IP addresses in any log output you share.

## Environment
- Home Assistant version:
- Integration version (from **Settings → Devices & Services → HA Docker Updater**):
- Docker Compose version (`docker compose version` on the Pi):
- Installation method: Manual / HACS
- Raspberry Pi OS version (`cat /etc/os-release`):

## Additional context
Any other context, screenshots, or information that might help diagnose the issue.