"""Centralized path constants and resource resolution for DGTCentaurMods.

This module defines all base paths used throughout the application.
All paths are absolute and should be used via import.

Database URI resolution is in db/uri.py
FEN operations are in managers/game.py
E-paper image writing is in services/chromecast.py
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

# Base installation directory
BASE_DIR = "/opt/DGTCentaurMods"

# Subdirectories under BASE_DIR
DB_DIR = f"{BASE_DIR}/db"
CONFIG_DIR = f"{BASE_DIR}/config"
TMP_DIR = f"{BASE_DIR}/tmp"
WEB_DIR = f"{BASE_DIR}/web"
WEB_STATIC_DIR = f"{WEB_DIR}/static"

# Resources directory relative to this file (works in both installed and dev environments)
# This file is at: <base>/paths.py, so resources is at: <base>/resources
RESOURCES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")

# User-customizable resources (takes precedence over system resources)
USER_RESOURCES_DIR = "/home/pi/resources"

# Specific files
FEN_LOG = f"{TMP_DIR}/fen.log"
EPAPER_STATIC_JPG = f"{WEB_STATIC_DIR}/epaper.jpg"
DEFAULT_DB_FILE = f"{DB_DIR}/centaur.db"


def get_resource_path(resource_file: str) -> str:
    """Return resource path from the resources folder or /home/pi/resources.
    
    Checks user resources directory first, then falls back to system resources.
    Rejects paths containing '..' for security.
    
    Args:
        resource_file: Name of the resource file (e.g., "Font.ttc")
        
    Returns:
        Absolute path to the resource file
    """
    if ".." in resource_file:
        return ""

    user_path = os.path.join(USER_RESOURCES_DIR, resource_file)
    if os.path.exists(user_path):
        return user_path
    return os.path.join(RESOURCES_DIR, resource_file)
