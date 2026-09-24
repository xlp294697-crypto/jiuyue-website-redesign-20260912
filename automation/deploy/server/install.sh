#!/bin/sh
# Bootstrap only through the operator's existing trusted server connection.
set -eu
if [ "$(id -u)" -ne 0 ]; then echo 'Run as root on the existing Linux host.' >&2; exit 2; fi
if [ "$#" -ne 3 ]; then echo 'Usage: sh install.sh ABSOLUTE_WEBROOT_SYMLINK ABSOLUTE_NGINX_CONFIG EXPECTED_COMMIT' >&2; exit 2; fi
for program in python3 git curl nginx systemctl install; do command -v "$program" >/dev/null; done
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -e /opt/jiuyue-static-pull ] || [ -L /opt/jiuyue-static-pull ] || [ -e /var/lib/jiuyue-static-pull ] || [ -L /var/lib/jiuyue-static-pull ]; then
  echo 'Installation or state already exists; refusing to overwrite it.' >&2; exit 2
fi
for unit in jiuyue-static-pull.service jiuyue-static-pull.timer; do
  if systemctl cat "$unit" >/dev/null 2>&1 || [ -e "/etc/systemd/system/$unit" ] || [ -L "/etc/systemd/system/$unit" ]; then
    echo 'A deployment unit already exists; refusing to overwrite it.' >&2; exit 2
  fi
done
python3 "$script_dir/deploy_pull.py" init --webroot "$1" --nginx-config "$2" --expected-commit "$3" --dry-run
install -d -o root -g root -m 0755 /opt/jiuyue-static-pull
install -o root -g root -m 0644 "$script_dir/deploy_pull.py" /opt/jiuyue-static-pull/deploy_pull.py
python3 /opt/jiuyue-static-pull/deploy_pull.py init --webroot "$1" --nginx-config "$2" --expected-commit "$3"
install -o root -g root -m 0644 "$script_dir/jiuyue-static-pull.service" /etc/systemd/system/jiuyue-static-pull.service
install -o root -g root -m 0644 "$script_dir/jiuyue-static-pull.timer" /etc/systemd/system/jiuyue-static-pull.timer
systemctl daemon-reload
# A real successful poll is required before enabling recurrence.
systemctl start jiuyue-static-pull.service
systemctl enable --now jiuyue-static-pull.timer
echo 'Installed. Current site and all previous releases remain available.'
