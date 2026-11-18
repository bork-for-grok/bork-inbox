#!/bin/bash
# Install bork-inbox as a systemd user service.
# Usage: deploy/install-user-unit.sh /path/to/private.env
set -euo pipefail
umask 077

env_file="${1:-}"
if [[ -z "${env_file}" ]]; then
  echo "usage: $0 /path/to/private.env" >&2
  exit 1
fi
env_file="$(readlink -f "${env_file}")"
if [[ ! -f "${env_file}" ]]; then
  echo "env file is missing: ${env_file}" >&2
  exit 1
fi
mode=$(stat -c '%a' "${env_file}")
if [[ "${mode}" != "600" ]]; then
  echo "env file mode is ${mode}, expected 600: ${env_file}" >&2
  exit 1
fi

install_dir="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -x "${install_dir}/.venv/bin/python" ]]; then
  echo "create the virtualenv first: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi
if ! systemctl --user show-environment >/dev/null 2>&1; then
  echo "the systemd user bus is not available" >&2
  exit 1
fi

unit_dst="${HOME}/.config/systemd/user/bork-inbox.service"
mkdir -p "$(dirname "${unit_dst}")"
sed -e "s#{{INSTALL_DIR}}#${install_dir}#g" -e "s#{{ENV_FILE}}#${env_file}#g" \
  "${install_dir}/deploy/bork-inbox.service" > "${unit_dst}"
chmod 644 "${unit_dst}"
systemctl --user daemon-reload
systemctl --user enable --now bork-inbox.service
systemctl --user --no-pager --full status bork-inbox.service
