#!/usr/bin/env bash
#
# Copium Proxy Shell Integration
#
# Automatically sets ANTHROPIC_BASE_URL if the copium proxy is running.
# Supports both bash and zsh.
#
# Usage:
#   Add to ~/.bashrc or ~/.zshrc:
#
#     export COPIUM_PROXY_PORT=8787  # Optional: customize port (default: 8787)
#     source /path/to/shell-integration.sh
#
# This script will:
#   1. Check if the proxy is running on the configured port
#   2. If running, set ANTHROPIC_BASE_URL
#   3. If not running, try to start the LaunchAgent
#   4. Provide helpful status messages (only on first load)
#

# Configuration: Port can be customized via environment variable
COPIUM_PROXY_PORT="${COPIUM_PROXY_PORT:-8787}"
COPIUM_PLIST_LABEL="com.copium.proxy"
USER_UID=$(id -u)

# Prevent duplicate loading (bash and zsh compatible)
if [[ -n "${COPIUM_SHELL_INTEGRATION_LOADED:-}" ]]; then
  return 0
fi
export COPIUM_SHELL_INTEGRATION_LOADED=1

# Check if proxy is running (fast path using lsof)
_copium_proxy_running() {
  lsof -iTCP:"${COPIUM_PROXY_PORT}" -sTCP:LISTEN -t >/dev/null 2>&1
}

# Try to start the LaunchAgent if not running
_copium_start_proxy() {
  local plist_path="${HOME}/Library/LaunchAgents/${COPIUM_PLIST_LABEL}.plist"

  # Check if LaunchAgent is installed
  if [[ ! -f "${plist_path}" ]]; then
    return 1
  fi

  # Try to bootstrap the LaunchAgent (idempotent - won't fail if already loaded)
  if launchctl bootstrap "gui/${USER_UID}" "${plist_path}" 2>/dev/null; then
    # Wait a moment for service to start
    sleep 1
    return 0
  fi

  return 1
}

# Main logic
if _copium_proxy_running; then
  # Proxy is running - set ANTHROPIC_BASE_URL
  export ANTHROPIC_BASE_URL="http://localhost:${COPIUM_PROXY_PORT}"
else
  # Proxy not running - try to start it
  if _copium_start_proxy && _copium_proxy_running; then
    # Successfully started - set ANTHROPIC_BASE_URL
    export ANTHROPIC_BASE_URL="http://localhost:${COPIUM_PROXY_PORT}"
    echo "✓ Copium proxy started on port ${COPIUM_PROXY_PORT}"
  else
    # Could not start - provide helpful message
    echo "⚠ Copium proxy not running on port ${COPIUM_PROXY_PORT}"
    echo "  Install with: cd /path/to/copium/examples/deployment/macos-launchagent && ./install.sh"
  fi
fi

# Cleanup helper functions (don't pollute shell namespace)
unset -f _copium_proxy_running _copium_start_proxy
