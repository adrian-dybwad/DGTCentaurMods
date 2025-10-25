#!/usr/bin/env bash
set -euo pipefail

log()  { printf "%s\n" "$*"; }
warn() { printf "WARN: %s\n" "$*" >&2; }
die()  { printf "ERROR: %s\n" "$*" >&2; exit 1; }
has_cmd()      { command -v "$1" >/dev/null 2>&1; }
require_path() { [[ -e "$1" ]] || die "Missing required: $1"; }

# Installation layout (device defaults)
VENVPY="/opt/DGTCentaurMods/.venv/bin/python"
APP_DIR="/opt/DGTCentaurMods/web"
APP_MAIN="$APP_DIR/app.py"
APP_HELPER="$APP_DIR/centaurflask.py"
DB_FILE="/opt/DGTCentaurMods/db/centaur.db"
NGINX_SITE_AVAILABLE="/etc/nginx/sites-available/centaurmods-web"
NGINX_SITE_ENABLED="/etc/nginx/sites-enabled/centaurmods-web"
WEB_SERVICE="centaurmods-web.service"
CORE_SERVICE="DGTCentaurMods.service"

# Preflight: required files and Python env
require_path "$APP_MAIN"
require_path "$APP_HELPER"
require_path "$VENVPY"
require_path "$DB_FILE"
require_path "$APP_DIR/templates"
require_path "$APP_DIR/static"

"$VENVPY" -c "import flask" >/dev/null 2>&1 || die "Flask not importable in venv ($VENVPY)"

# Preflight: services
if has_cmd systemctl; then
  systemctl -q cat "$WEB_SERVICE"  >/dev/null 2>&1 || die "Missing systemd unit: $WEB_SERVICE"
  systemctl -q cat "$CORE_SERVICE" >/dev/null 2>&1 || die "Missing systemd unit: $CORE_SERVICE"
  systemctl is-active --quiet "$CORE_SERVICE" || warn "$CORE_SERVICE not active"
  systemctl is-active --quiet "$WEB_SERVICE"  || warn "$WEB_SERVICE not active"
else
  warn "systemctl not found; skipping service checks"
fi

# Preflight: nginx configuration (best-effort)
if has_cmd nginx || (has_cmd systemctl && systemctl -q cat nginx >/dev/null 2>&1); then
  if [[ -e "$NGINX_SITE_AVAILABLE" ]]; then
    if ! grep -q "proxy_pass http://127.0.0.1:5000;" "$NGINX_SITE_AVAILABLE"; then
      warn "nginx site missing expected proxy_pass to 127.0.0.1:5000"
    fi
  else
    warn "nginx site config not found at $NGINX_SITE_AVAILABLE"
  fi
  [[ -e "$NGINX_SITE_ENABLED" ]] || warn "nginx site not enabled (missing $NGINX_SITE_ENABLED)"
else
  warn "nginx not detected; assuming direct Flask access"
fi

# Base URL handling
BASE_URL="${1:-${BASE_URL:-}}"
if [[ -z "${BASE_URL}" ]]; then
  BASE_URL="http://127.0.0.1"
fi

# if no port specified and :80 fails, try :5000 automatically
function curl_ok() { curl -fsSL --max-time 5 "$1" >/dev/null 2>&1; }

PRIMARY_URL="${BASE_URL}"
if ! curl_ok "${PRIMARY_URL}/"; then
  if [[ "${PRIMARY_URL}" != *":"* ]]; then
    if curl_ok "${PRIMARY_URL}:5000/"; then
      PRIMARY_URL+=":5000"
    fi
  fi
fi

printf "Using base URL: %s\n" "${PRIMARY_URL}"

# small retry helper
attempts=0; max_attempts=20; sleep_s=1
until curl_ok "${PRIMARY_URL}/"; do
  attempts=$((attempts+1))
  if (( attempts >= max_attempts )); then
    echo "ERROR: Web root not responding at ${PRIMARY_URL}/" >&2
    exit 1
  fi
  sleep "${sleep_s}"
  printf "." >&2
done
echo

# 1) Homepage renders and contains known text/title
home_html=$(curl -fsSL --max-time 10 "${PRIMARY_URL}/")
if ! grep -qiE "<title>\s*DGT Centaur Board\s*</title>|DGT Centaur Mods" <<<"${home_html}"; then
  echo "ERROR: Homepage missing expected branding/title" >&2
  exit 1
fi

# 2) /fen returns a plausible FEN
fen=$(curl -fsSL --max-time 5 "${PRIMARY_URL}/fen" || true)
if [[ -z "${fen}" ]] || ! grep -qE "\s(w|b)\s" <<<"${fen}"; then
  echo "ERROR: /fen did not return a plausible FEN (got: '${fen}')" >&2
  exit 1
fi

# 3) /engines returns JSON (best-effort, use jq if available)
engines=$(curl -fsSL --max-time 5 "${PRIMARY_URL}/engines" || true)
if command -v jq >/dev/null 2>&1; then
  echo "${engines}" | jq -e . >/dev/null 2>&1 || { echo "ERROR: /engines not valid JSON" >&2; exit 1; }
else
  [[ "${engines}" =~ ^\{|^\[ ]] || { echo "ERROR: /engines not JSON-like" >&2; exit 1; }
fi

printf "OK: Web smoke tests passed at %s\n" "${PRIMARY_URL}"


