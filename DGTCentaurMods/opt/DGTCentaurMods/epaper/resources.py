"""Resource path resolution for epaper widgets.

This module provides resource path resolution without importing managers,
avoiding the circular import: epaper -> managers -> emulators -> board -> epaper.

The logic mirrors AssetManager.get_resource_path() but has no external dependencies.
"""

import os


# Base directories - must match AssetManager constants
RESOURCES_DIR = "/opt/DGTCentaurMods/resources"
USER_RESOURCES_DIR = "/home/pi/resources"


def get_resource_path(resource_file: str) -> str:
    """Return resource path from the resources folder or /home/pi/resources.
    
    Checks user resources directory first, then falls back to system resources.
    Rejects paths containing '..' for security.
    
    Args:
        resource_file: Name of the resource file (e.g., "Font.ttc")
        
    Returns:
        Absolute path to the resource file, or empty string if path is invalid
    """
    if ".." in resource_file:
        return ""
    
    user_path = os.path.join(USER_RESOURCES_DIR, resource_file)
    if os.path.exists(user_path):
        return user_path
    return os.path.join(RESOURCES_DIR, resource_file)
