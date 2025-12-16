"""Asset and path management for DGTCentaurMods.

This module provides centralized management for:
- Resource file resolution (fonts, images, sprites)
- Runtime directory paths (database, config, temp, web)
- FEN log operations
- E-paper static image operations

All path-related operations should go through AssetManager to avoid
scattering hardcoded paths across the codebase.
"""

# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# DGTCentaur Mods is free software: you can redistribute
# it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.
#
# DGTCentaur Mods is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see
#
# https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md
#
# This and any other notices must remain intact and unaltered in any
# distribution, modification, variant, or derivative of this software.

import os
import shutil
from typing import Optional

from DGTCentaurMods.board.logging import log


class AssetManager:
    """Centralized manager for resource paths and runtime file operations.
    
    Provides static methods for:
    - Resource file resolution (fonts, images)
    - Runtime directory management
    - Database URI resolution
    - FEN log read/write operations
    - E-paper static image operations
    
    All methods are static - no instance required.
    """

    # Base directories
    BASE_DIR = "/opt/DGTCentaurMods"
    DB_DIR = f"{BASE_DIR}/db"
    CONFIG_DIR = f"{BASE_DIR}/config"
    TMP_DIR = f"{BASE_DIR}/tmp"
    WEB_DIR = f"{BASE_DIR}/web"
    WEB_STATIC_DIR = f"{WEB_DIR}/static"
    RESOURCES_DIR = f"{BASE_DIR}/resources"
    USER_RESOURCES_DIR = "/home/pi/resources"

    # Files
    FEN_LOG = f"{TMP_DIR}/fen.log"
    DEFAULT_DB_FILE = f"{DB_DIR}/centaur.db"
    EPAPER_STATIC_JPG = f"{WEB_STATIC_DIR}/epaper.jpg"

    # Defaults
    DEFAULT_START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

    # -------------------------------------------------------------------------
    # Resource Path Resolution
    # -------------------------------------------------------------------------

    @staticmethod
    def get_resource_path(resource_file: str) -> str:
        """Return resource path from the resources folder or /home/pi/resources.
        
        Checks user resources directory first, then falls back to system resources.
        Rejects paths containing '..' for security.
        
        Args:
            resource_file: Name of the resource file (e.g., "Font.ttc")
            
        Returns:
            Absolute path to the resource file
        """
        if resource_file.find("..") >= 0:
            return ""

        user_path = os.path.join(AssetManager.USER_RESOURCES_DIR, resource_file)
        if os.path.exists(user_path):
            return user_path
        return os.path.join(AssetManager.RESOURCES_DIR, resource_file)

    # -------------------------------------------------------------------------
    # Directory Utilities
    # -------------------------------------------------------------------------

    @staticmethod
    def ensure_parent_dir(path: str) -> bool:
        """Ensure the parent directory of the given path exists.
        
        Args:
            path: File path whose parent directory should be created
            
        Returns:
            True if directory exists or was created, False if creation failed
        """
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            try:
                os.makedirs(parent, exist_ok=True)
            except PermissionError:
                log.error(
                    f"Permission denied creating directory: {parent}. "
                    "This may indicate a permissions issue or running outside "
                    "the installed environment."
                )
                return False
        return True

    @staticmethod
    def ensure_runtime_layout() -> bool:
        """Ensure base runtime directories under /opt exist.
        
        Creates: /opt/DGTCentaurMods/{db,config,tmp}
        
        Returns:
            True if all directories exist or were created, False if any failed
        """
        success = True
        for d in (AssetManager.DB_DIR, AssetManager.CONFIG_DIR, AssetManager.TMP_DIR):
            if not os.path.isdir(d):
                try:
                    os.makedirs(d, exist_ok=True)
                except PermissionError:
                    log.error(
                        f"Permission denied creating directory: {d}. "
                        "This may indicate a permissions issue or running outside "
                        "the installed environment."
                    )
                    success = False
        return success

    @staticmethod
    def seed_default_config() -> None:
        """Seed centaur.ini from defaults if missing.
        
        Copies defaults/config/centaur.ini into config/ if not present.
        """
        from DGTCentaurMods.board.settings import Settings
        dst = Settings.configfile
        src = Settings.defconfigfile
        AssetManager.ensure_parent_dir(dst)
        if not os.path.isfile(dst) and os.path.isfile(src):
            shutil.copyfile(src, dst)

    @staticmethod
    def bootstrap_runtime() -> None:
        """Create directories and seed defaults; safe to call repeatedly."""
        AssetManager.ensure_runtime_layout()
        AssetManager.seed_default_config()

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------

    @staticmethod
    def _normalize_sqlite_uri(db_path: str) -> str:
        """Return a SQLAlchemy sqlite URI for the provided absolute path."""
        return f"sqlite:///{db_path}"

    @staticmethod
    def get_database_uri() -> str:
        """Resolve the database URI using config override or default under /opt.
        
        Precedence:
        1) centaur.ini [DATABASE].database_uri if set (accept any SQLAlchemy URI)
        2) sqlite database at /opt/DGTCentaurMods/db/centaur.db
        
        Returns:
            SQLAlchemy-compatible database URI string
        """
        try:
            from DGTCentaurMods.board.settings import Settings
            configured = Settings.read('DATABASE', 'database_uri', '').strip()
        except Exception:
            configured = ''

        if configured:
            if "://" in configured:
                return configured
            path = configured
            if not os.path.isabs(path):
                path = os.path.join(AssetManager.DB_DIR, path)
            AssetManager.ensure_parent_dir(path)
            return AssetManager._normalize_sqlite_uri(path)

        AssetManager.ensure_parent_dir(AssetManager.DEFAULT_DB_FILE)
        return AssetManager._normalize_sqlite_uri(AssetManager.DEFAULT_DB_FILE)

    # -------------------------------------------------------------------------
    # FEN Log Operations
    # -------------------------------------------------------------------------

    @staticmethod
    def get_fen_log_path() -> str:
        """Return the fen.log path and ensure its parent directory exists."""
        AssetManager.ensure_parent_dir(AssetManager.FEN_LOG)
        return AssetManager.FEN_LOG

    @staticmethod
    def open_fen_log(mode: str = "r"):
        """Open fen.log with the given mode, ensuring directory for write modes.
        
        If mode implies writing (contains 'w', 'a' or '+'), the parent directory
        will be created first. For text modes, UTF-8 encoding is used.
        
        Args:
            mode: File open mode (e.g., "r", "w", "a")
            
        Returns:
            Open file handle
        """
        if any(flag in mode for flag in ("w", "a", "+")):
            AssetManager.ensure_parent_dir(AssetManager.FEN_LOG)
        if "b" in mode:
            return open(AssetManager.FEN_LOG, mode)
        return open(AssetManager.FEN_LOG, mode, encoding="utf-8")

    @staticmethod
    def write_fen_log(text: str) -> None:
        """Write text to fen.log atomically where possible.
        
        Ensures parent directory exists and writes using UTF-8.
        
        Args:
            text: FEN string to write
        """
        AssetManager.ensure_parent_dir(AssetManager.FEN_LOG)
        log.info(f"Writing to {AssetManager.FEN_LOG}: {text}")
        with open(AssetManager.FEN_LOG, "w", encoding="utf-8") as f:
            f.write(text)

    @staticmethod
    def get_current_fen() -> str:
        """Return the current FEN from fen.log.
        
        Behavior:
        - If fen.log exists and has content, return its first line as-is.
        - If fen.log is missing, return the starting FEN.
        - If fen.log is empty, return the starting FEN.
        
        Returns:
            Current FEN string or default starting position
        """
        try:
            with AssetManager.open_fen_log("r") as f:
                curfen = f.readline().strip()
        except FileNotFoundError:
            return AssetManager.DEFAULT_START_FEN
        log.info(f"Reading from {AssetManager.FEN_LOG}: {curfen}")
        return curfen or AssetManager.DEFAULT_START_FEN

    @staticmethod
    def get_current_placement() -> str:
        """Read the placement from the current fen."""
        return AssetManager.get_current_fen().split(" ")[0]

    @staticmethod
    def get_current_turn() -> str:
        """Read the turn from the current fen."""
        return AssetManager.get_current_fen().split(" ")[1]

    @staticmethod
    def get_current_castling() -> str:
        """Read the castling from the current fen."""
        return AssetManager.get_current_fen().split(" ")[2]

    @staticmethod
    def get_current_en_passant() -> str:
        """Read the en passant from the current fen."""
        return AssetManager.get_current_fen().split(" ")[3]

    @staticmethod
    def get_current_halfmove_clock() -> str:
        """Read the halfmove clock from the current fen."""
        return AssetManager.get_current_fen().split(" ")[4]

    # -------------------------------------------------------------------------
    # Web/E-paper Static Assets
    # -------------------------------------------------------------------------

    @staticmethod
    def get_web_static_dir() -> str:
        """Return absolute path to the web static directory under /opt."""
        return AssetManager.WEB_STATIC_DIR

    @staticmethod
    def get_epaper_static_jpg_path(ensure_parent: bool = False) -> str:
        """Return absolute path to web/static/epaper.jpg.
        
        Args:
            ensure_parent: If True, the parent directory is created if missing
            
        Returns:
            Absolute path to epaper.jpg
        """
        if ensure_parent:
            AssetManager.ensure_parent_dir(AssetManager.EPAPER_STATIC_JPG)
        return AssetManager.EPAPER_STATIC_JPG

    @staticmethod
    def write_epaper_static_jpg(image) -> str:
        """Write the provided Pillow Image to web/static/epaper.jpg and return the path.
        
        The image will be converted to a JPEG-compatible mode if needed.
        The image is rotated 180 degrees before saving to correct orientation
        for Chromecast streaming.
        
        Args:
            image: PIL Image to save
            
        Returns:
            Path where image was saved
            
        Raises:
            TypeError: If image is not a PIL Image
        """
        path = AssetManager.get_epaper_static_jpg_path(ensure_parent=True)
        from PIL import Image
        img = image
        if not isinstance(img, Image.Image):
            raise TypeError("write_epaper_static_jpg expects a PIL Image")
        if img.mode not in ("L", "RGB"):
            img = img.convert("L")
        # Rotate 180 degrees to correct orientation for streaming
        img = img.rotate(180)
        img.save(path, format="JPEG")
        return path


# Perform a light-weight bootstrap at import time.
# Kept minimal and idempotent to avoid side effects.
try:
    AssetManager.bootstrap_runtime()
except Exception:
    # Swallow to avoid breaking runtime if filesystem is read-only during import
    pass
