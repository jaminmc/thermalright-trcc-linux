#!/usr/bin/env bash
# Install the root LaunchDaemon that serves powermetrics over
# /var/run/trcc-powermetrics.sock (TRCC stays unprivileged).
# Usage: from this directory, run: sudo ./install-helper.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_BIN="${ROOT}/trcc-powermetrics-helper"
SRC_PLIST="${ROOT}/com.thermalright.trcc.powermetrics.plist"
DST_BIN="/Library/PrivilegedHelperTools/trcc-powermetrics-helper"
DST_PLIST="/Library/LaunchDaemons/com.thermalright.trcc.powermetrics.plist"
LABEL="com.thermalright.trcc.powermetrics"

if [[ "$(id -u)" -ne 0 ]]; then
	echo "Install requires root. Run: sudo \"$0\"" >&2
	exit 1
fi

if [[ ! -f "${SRC_PLIST}" ]]; then
	echo "Missing ${SRC_PLIST}" >&2
	exit 1
fi

if [[ ! -x "${SRC_BIN}" ]]; then
	if [[ -f "${ROOT}/Makefile" ]] && command -v make >/dev/null; then
		echo "Building ${SRC_BIN}..." >&2
		( cd "${ROOT}" && make )
	fi
fi

if [[ ! -x "${SRC_BIN}" ]]; then
	echo "Missing executable ${SRC_BIN} (build with: make in ${ROOT})" >&2
	exit 1
fi

install -d -m 0755 -o root -g wheel /Library/PrivilegedHelperTools
install -m 0755 -o root -g wheel "${SRC_BIN}" "${DST_BIN}"
install -m 0644 -o root -g wheel "${SRC_PLIST}" "${DST_PLIST}"

# Reload job (ignore errors if not loaded)
launchctl bootout "system/${LABEL}" 2>/dev/null || true
launchctl bootstrap system "${DST_PLIST}"

echo "Installed ${DST_BIN} and ${DST_PLIST}."
echo "TRCC will use ${DST_BIN} via /var/run/trcc-powermetrics.sock (override with TRCC_POWERMETRICS_SOCKET if needed)."
echo "Test from a login user:  trcc powermetrics-helper-test"
echo "Or pytest (macOS only):  TRCC_TEST_POWERMETRICS_HELPER=1 pytest tests/adapters/system/macos/test_powermetrics_ipc.py -k powermetrics_helper_live"
