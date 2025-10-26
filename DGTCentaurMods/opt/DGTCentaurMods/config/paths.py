"""Centralized runtime paths for DGTCentaurMods.

This module defines canonical locations for runtime files under /opt.
It avoids scattering hardcoded paths across the codebase.

Assumptions:
- Runtime base directory is /opt/DGTCentaurMods on target devices.
- An optional override database URI may be set in centaur.ini under [DATABASE].
"""

import os
import shutil
from typing import Optional


# Base directories
BASE_DIR = "/opt/DGTCentaurMods"
DB_DIR = f"{BASE_DIR}/db"
CONFIG_DIR = f"{BASE_DIR}/config"
TMP_DIR = f"{BASE_DIR}/tmp"

# Files
FEN_LOG = f"{TMP_DIR}/fen.log"
DEFAULT_DB_FILE = f"{DB_DIR}/centaur.db"

# Defaults
DEFAULT_START_FEN = (
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
)


def ensure_parent_dir(path: str) -> None:
    """Ensure the parent directory of the given path exists."""
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


def _normalize_sqlite_uri(db_path: str) -> str:
    """Return a SQLAlchemy sqlite URI for the provided absolute path."""
    # SQLAlchemy absolute sqlite path syntax requires four slashes
    return f"sqlite:///{db_path}"


def get_database_uri() -> str:
    """Resolve the database URI using config override or default under /opt.

    Precedence:
    1) centaur.ini [DATABASE].database_uri if set (accept any SQLAlchemy URI)
    2) sqlite database at /opt/DGTCentaurMods/db/centaur.db
    """
    try:
        # Lazy import to avoid any potential import cycles
        from DGTCentaurMods.board.settings import Settings  # type: ignore
        configured = Settings.read('DATABASE', 'database_uri', '').strip()
    except Exception:
        configured = ''

    if configured:
        # If user provided a full SQLAlchemy URI, use it as-is
        if "://" in configured:
            return configured
        # Otherwise treat it as a filesystem path for sqlite
        path = configured
        if not os.path.isabs(path):
            path = os.path.join(DB_DIR, path)
        ensure_parent_dir(path)
        return _normalize_sqlite_uri(path)

    # Default to our packaged location
    ensure_parent_dir(DEFAULT_DB_FILE)
    return _normalize_sqlite_uri(DEFAULT_DB_FILE)


def ensure_runtime_layout() -> None:
    """Ensure base runtime directories under /opt exist.

    Creates: /opt/DGTCentaurMods/{db,config,tmp}
    """
    for d in (DB_DIR, CONFIG_DIR, TMP_DIR):
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)


def seed_default_config() -> None:
    """Seed centaur.ini from defaults if missing.

    Copies defaults/config/centaur.ini into config/ if not present.
    """
    from DGTCentaurMods.board.settings import Settings  # lazy import
    dst = Settings.configfile
    src = Settings.defconfigfile
    # Create config dir
    ensure_parent_dir(dst)
    if not os.path.isfile(dst) and os.path.isfile(src):
        shutil.copyfile(src, dst)


def bootstrap_runtime() -> None:
    """Create directories and seed defaults; safe to call repeatedly."""
    ensure_runtime_layout()
    seed_default_config()


# Perform a light-weight bootstrap at import time.
# Kept minimal and idempotent to avoid side effects.
try:
    bootstrap_runtime()
except Exception:
    # Swallow to avoid breaking runtime if filesystem is read-only during import
    pass


def get_fen_log_path() -> str:
    """Return the fen.log path and ensure its parent directory exists."""
    ensure_parent_dir(FEN_LOG)
    return FEN_LOG


def open_fen_log(mode: str = "r"):
    """Open fen.log with the given mode, ensuring directory for write modes.

    If mode implies writing (contains 'w', 'a' or '+'), the parent directory
    will be created first. For text modes, UTF-8 encoding is used.
    """
    if any(flag in mode for flag in ("w", "a", "+")):
        ensure_parent_dir(FEN_LOG)
    if "b" in mode:
        return open(FEN_LOG, mode)
    return open(FEN_LOG, mode, encoding="utf-8")


def write_fen_log(text: str) -> None:
    """Write text to fen.log atomically where possible.

    Ensures parent directory exists and writes using UTF-8.
    """
    ensure_parent_dir(FEN_LOG)
    # Simple write; atomic swap could be added if needed
    with open(FEN_LOG, "w", encoding="utf-8") as f:
        f.write(text)


def get_current_fen() -> str:
    """Return the current FEN from fen.log.

    Behavior:
    - If fen.log exists and has content, return its first line as-is.
    - If fen.log is missing, return the starting FEN.
    - If fen.log is empty, return the starting FEN.

    """
    try:
        with open_fen_log("r") as f:
            curfen = f.readline().strip()
    except FileNotFoundError:
        return DEFAULT_START_FEN

    return curfen or DEFAULT_START_FEN

def get_current_placement() -> str:
    """Read the placement from the current fen."""
    return get_current_fen().split(" ")[0]

def get_current_turn() -> str:
    """Read the turn from the current fen."""
    return get_current_fen().split(" ")[1]

def get_current_castling() -> str:
    """Read the castling from the current fen."""
    return get_current_fen().split(" ")[2]

def get_current_en_passant() -> str:
    """Read the en passant from the current fen."""
    return get_current_fen().split(" ")[3]

def get_current_halfmove_clock() -> str:
    """Read the halfmove clock from the current fen."""
    return get_current_fen().split(" ")[4]