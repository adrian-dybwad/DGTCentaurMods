#!/usr/bin/env bash

# Reset Pi Cleanup Script for DGTCentaurMods (Raspberry Pi OS trixie)
# This script purges the dgtcentaurmods package and reverts system changes
# made by the package's maintainer scripts. It is idempotent and safe to re-run.

set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

YES=0
DRY_RUN=0

log_info() { echo "[INFO] $*"; }
log_warn() { echo "[WARN] $*"; }
log_err()  { echo "[ERROR] $*" >&2; }

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "+ $*"
  else
    eval "$@"
  fi
}

require_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    log_err "Run as root (sudo)."; exit 1
  fi
}

usage() {
  cat <<'USAGE'
Usage: reset.sh [--yes] [--dry-run]

Options:
  --yes       Assume "yes" to all prompts (non-interactive)
  --dry-run   Print actions without executing
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) log_err "Unknown option: $1"; usage; exit 2 ;;
  esac
  shift
done

require_root

# Paths and constants
PACKAGE_NAME="dgtcentaurmods"
DGTCM_DIR="/opt/DGTCentaurMods"
DIST_PKG_SYMLINK="/usr/lib/python3/dist-packages/DGTCentaurMods"
NGINX_SITES_AVAILABLE="/etc/nginx/sites-available"
NGINX_SITES_ENABLED="/etc/nginx/sites-enabled"
NGINX_DEFAULT_SITE="${NGINX_SITES_AVAILABLE}/default"
NGINX_CENTAUR_SITE="${NGINX_SITES_AVAILABLE}/centaurmods-web"
CONFIG_TXT="/boot/firmware/config.txt"
CMDLINE_TXT="/boot/firmware/cmdline.txt"
BT_MAIN="/etc/bluetooth/main.conf"
BT_PINCONF="/etc/bluetooth/pin.conf"
MACHINE_INFO="/etc/machine-info"
ENGINES_DIR="/home/pi/centaur/engines"
FEN_LOG="/home/pi/centaur/fen.log"

# Detect firmware mount (fallback for older releases)
if [ ! -f "$CONFIG_TXT" ] && [ -f "/boot/config.txt" ]; then
  CONFIG_TXT="/boot/config.txt"
fi
if [ ! -f "$CMDLINE_TXT" ] && [ -f "/boot/cmdline.txt" ]; then
  CMDLINE_TXT="/boot/cmdline.txt"
fi

stop_services() {
  log_info "Stopping DGTCentaurMods-related services (ignore errors)"
  local units=(
    rfcomm.service
    DGTCentaurModsWeb.service
    DGTCentaurMods.service
    var-run-sdp.path
    var-run-sdp.service
    stopDGTController.service
  )
  for u in "${units[@]}"; do
    run "systemctl stop $u" || true
  done
}

remove_units_and_overrides() {
  log_info "Disabling and removing lingering systemd units/overrides"
  local files=(
    /etc/systemd/system/DGTCentaurModsWeb.service
    /etc/systemd/system/DGTCentaurMods.service
    /etc/systemd/system/var-run-sdp.path
    /etc/systemd/system/var-run-sdp.service
    /etc/systemd/system/stopDGTController.service
    /etc/systemd/system/bluetooth.service.d/01-disable-sap-plugin.conf
    /etc/systemd/system/bthelper@.service.d/01-add-delay.conf
  )
  for f in "${files[@]}"; do
    if [ -e "$f" ]; then
      run "systemctl disable $(basename \"$f\")" || true
      run "rm -f \"$f\""
    fi
  done
  # Remove empty override directories if left behind
  for d in /etc/systemd/system/bluetooth.service.d /etc/systemd/system/bthelper@.service.d; do
    if [ -d "$d" ] && [ -z "$(ls -A "$d" 2>/dev/null || true)" ]; then
      run "rmdir \"$d\"" || true
    fi
  done
  run "systemctl daemon-reload"
  # Remove deprecated old web service unit if still present
  if [ -e "/etc/systemd/system/centaurmods-web.service" ]; then
    run "systemctl disable centaurmods-web.service" || true
    run "rm -f /etc/systemd/system/centaurmods-web.service"
    run "systemctl daemon-reload"
  fi
}

revert_nginx() {
  log_info "Reverting nginx site configuration"
  # Remove centaurmods site
  if [ -e "$NGINX_CENTAUR_SITE" ]; then
    run "rm -f \"$NGINX_CENTAUR_SITE\""
  fi
  if [ -L "${NGINX_SITES_ENABLED}/centaurmods-web" ] || [ -e "${NGINX_SITES_ENABLED}/centaurmods-web" ]; then
    run "rm -f \"${NGINX_SITES_ENABLED}/centaurmods-web\""
  fi
  # Restore default site symlink if available
  if [ -f "$NGINX_DEFAULT_SITE" ]; then
    run "ln -snf \"$NGINX_DEFAULT_SITE\" \"${NGINX_SITES_ENABLED}/default\""
  fi
  # Test and reload nginx if installed
  if command -v nginx >/dev/null 2>&1; then
    if run "nginx -t"; then
      run "systemctl reload nginx" || true
    else
      log_warn "nginx configuration test failed; skipping reload"
    fi
  fi
}

revert_bluetooth() {
  log_info "Reverting Bluetooth configuration"
  # main.conf
  if [ -f "${BT_MAIN}.bak" ] && grep -q "#dgtcentaurmods" "$BT_MAIN"; then
    run "mv -f \"${BT_MAIN}.bak\" \"$BT_MAIN\""
  else
    # Undo our edits if present
    if [ -f "$BT_MAIN" ]; then
      run "sed -i 's/^JustWorksRepairing = always/JustWorksRepairing = never/' \"$BT_MAIN\"" || true
      # Re-comment timeouts if we uncommented them
      run "sed -i 's/^\(DiscoverableTimeout\)/#\1/' \"$BT_MAIN\"" || true
      run "sed -i 's/^\(PairableTimeout\)/#\1/' \"$BT_MAIN\"" || true
      run "sed -i '/#dgtcentaurmods/d' \"$BT_MAIN\"" || true
    fi
  fi

  # pin.conf created with "* *"
  if [ -f "$BT_PINCONF" ] && grep -qx "\* \*" "$BT_PINCONF"; then
    run "rm -f \"$BT_PINCONF\""
  fi

  # machine-info created with fixed PRETTY_HOSTNAME
  if [ -f "$MACHINE_INFO" ] && grep -qx "PRETTY_HOSTNAME=PCS-REVII-081500" "$MACHINE_INFO"; then
    run "rm -f \"$MACHINE_INFO\""
  fi
}

revert_firmware_config() {
  log_info "Reverting firmware serial/SPI configuration"

  # config.txt
  if [ -f "$CONFIG_TXT" ]; then
    if [ -f "${CONFIG_TXT}.bak" ] && grep -q "#dgtcentaurmods" "$CONFIG_TXT"; then
      run "mv -f \"${CONFIG_TXT}.bak\" \"$CONFIG_TXT\""
    else
      # Remove our overlay and marker; re-comment UART if we un-commented it
      run "sed -i '/^dtoverlay=spi1-.*cs/d' \"$CONFIG_TXT\"" || true
      run "sed -i 's/^enable_uart=1$/#enable_uart=1/' \"$CONFIG_TXT\"" || true
      run "sed -i '/#dgtcentaurmods/d' \"$CONFIG_TXT\"" || true
    fi
  fi

  # cmdline.txt: restore if bak else ensure default consoles are present and deduped
  if [ -f "$CMDLINE_TXT" ]; then
    if [ -f "${CMDLINE_TXT}.bak" ]; then
      run "mv -f \"${CMDLINE_TXT}.bak\" \"$CMDLINE_TXT\""
    else
      local line
      line="$(cat "$CMDLINE_TXT")"
      case "$line" in *"console=serial0,115200"* ) : ;; *) line="console=serial0,115200 $line" ;; esac
      case "$line" in *"console=tty1"* ) : ;; *) line="console=tty1 $line" ;; esac
      # Deduplicate tokens while preserving order
      line="$(echo "$line" | awk '{for(i=1;i<=NF;i++){if(!seen[$i]++){out=out $i " "}}} END{print out}')"
      run "printf '%s\n' \"$line\" > \"$CMDLINE_TXT\""
    fi
  fi
}

undo_python_site() {
  log_info "Removing Python site-package symlink and venv"
  if [ -L "$DIST_PKG_SYMLINK" ]; then
    local target
    target="$(readlink -f "$DIST_PKG_SYMLINK" || true)"
    if [ "$target" = "$DGTCM_DIR" ]; then
      run "rm -f \"$DIST_PKG_SYMLINK\""
    fi
  fi
  if [ -d "${DGTCM_DIR}/.venv" ]; then
    run "rm -rf \"${DGTCM_DIR}/.venv\""
  fi
}

remove_engines_and_data() {
  log_info "Removing engines and data under /home/pi/centaur"
  if [ -d "$ENGINES_DIR" ]; then
    run "rm -rf \"$ENGINES_DIR\"/*" || true
  fi
  if [ -f "$FEN_LOG" ]; then
    run "rm -f \"$FEN_LOG\"" || true
  fi
}

restore_hostname_and_groups() {
  log_info "Restoring hostname and removing extra group memberships"
  local current
  current="$(hostname)"
  if [ "$current" = "dgtcentaur" ]; then
    # Update hostname back to raspberrypi
    if command -v hostnamectl >/dev/null 2>&1; then
      run "hostnamectl set-hostname raspberrypi" || true
    fi
    # Ensure /etc/hostname and /etc/hosts are consistent
    if [ -f /etc/hostname ]; then
      run "sed -i 's/^dgtcentaur$/raspberrypi/' /etc/hostname" || true
    fi
    if [ -f /etc/hosts ]; then
      run "sed -i 's/\bdgtcentaur\b/raspberrypi/g' /etc/hosts" || true
    fi
  fi
  # Remove pi from groups added by postinst
  run "gpasswd -d pi gpio" || true
  run "gpasswd -d pi kmem" || true
}

purge_package() {
  log_info "Purging package ${PACKAGE_NAME} (ignore errors if not installed)"
  run "apt-get -y purge ${PACKAGE_NAME}" || true
  run "apt-get -y autoremove" || true
  run "apt-get -y autoclean" || true
  # Remove installed directory if left behind
  if [ -d "$DGTCM_DIR" ]; then
    run "rm -rf \"$DGTCM_DIR\""
  fi
}

cleanup_opt_root() {
  log_info "Removing DGTCM files from /opt"
  local ours=(
    DGTCentaurMods
    bt_state.sh
    maia_weights.sh
    README-maia-weights.md
    run.sh
    setup.sh
    test_promotion.sh
    test.sh
    test_serial_helper.py
  )
  for item in "${ours[@]}"; do
    if [ -e "/opt/${item}" ]; then
      run "rm -rf \"/opt/${item}\""
    fi
  done

  # After removing our files, check remaining contents in /opt
  if [ -d /opt ]; then
    local remaining
    remaining=$(ls -A /opt 2>/dev/null || true)
    if [ -n "$remaining" ]; then
      log_warn "/opt is not empty after DGTCM cleanup. Entries: $(echo "$remaining" | tr '\n' ' ')"
      if [ "$YES" -eq 1 ]; then
        log_info "--yes provided; removing entire /opt"
        run "rm -rf /opt"
      else
        if [ -t 0 ] && [ -t 1 ]; then
          read -r -p "Remove entire /opt directory (y/N)? " reply || reply="n"
        else
          reply="n"
        fi
        case "${reply:-n}" in
          y|Y|yes|YES)
            run "rm -rf /opt" ;;
          *)
            log_info "Keeping /opt as-is" ;;
        esac
      fi
    else
      # Empty /opt -> remove to restore pristine state
      run "rmdir /opt" || true
    fi
  fi
}

reenable_rfcomm() {
  if systemctl list-unit-files | grep -q '^rfcomm.service'; then
    log_info "Re-enabling rfcomm.service"
    run "systemctl enable rfcomm.service" || true
  fi
}

summary() {
  echo
  log_info "Cleanup completed. It is recommended to reboot the system."
}

# Execute steps
stop_services
remove_units_and_overrides
revert_nginx
revert_bluetooth
revert_firmware_config
undo_python_site
remove_engines_and_data
restore_hostname_and_groups
purge_package
cleanup_opt_root
reenable_rfcomm
run "systemctl daemon-reload"
summary


