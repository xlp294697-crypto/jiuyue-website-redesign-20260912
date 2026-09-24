#!/bin/sh
# Stop future runs and wait for any current transaction. Never delete a release.
set -eu
if [ "$(id -u)" -ne 0 ]; then echo 'Run as root.' >&2; exit 2; fi
systemctl disable --now jiuyue-static-pull.timer
while :; do
  run_state=$(systemctl show --property=ActiveState --value jiuyue-static-pull.service)
  case "$run_state" in
    active|activating|reloading|deactivating) sleep 2 ;;
    *) break ;;
  esac
done
echo 'Future pulls disabled. Service, configuration, state and releases retained.'
