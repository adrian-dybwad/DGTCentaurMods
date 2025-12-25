"""
Sound settings module.

Provides functions to query and modify sound settings for different
event types. Settings are stored in the centaur.ini configuration file.
"""

from typing import Optional

try:
    from universalchess.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

try:
    from universalchess.board.settings import Settings
except ImportError:
    Settings = None
    log.warning("[SoundSettings] Settings module not available")


# Sound setting keys and their defaults
# Each setting controls whether beeps are played for that event type
SOUND_SETTINGS = {
    'enabled': ('sound', 'sound', 'on'),           # Master enable (existing setting)
    'key_press': ('sound', 'key_press', 'on'),     # Beep on button press
    'error': ('sound', 'error', 'on'),             # Beep on errors
    'game_event': ('sound', 'game_event', 'on'),   # Beep on game events (check, checkmate, etc.)
    'piece_event': ('sound', 'piece_event', 'off'), # Beep on piece lift/place (off by default)
}


def get_sound_settings() -> dict:
    """Get all sound settings.
    
    Returns:
        Dictionary with setting names as keys and bool values
    """
    settings = {}
    
    if Settings is None:
        # Return defaults if Settings not available
        for key, (section, option, default) in SOUND_SETTINGS.items():
            settings[key] = default == 'on'
        return settings
    
    for key, (section, option, default) in SOUND_SETTINGS.items():
        value = Settings.read(section, option, default)
        settings[key] = value == 'on'
    
    return settings


def get_sound_setting(key: str) -> bool:
    """Get a specific sound setting.
    
    Args:
        key: Setting key from SOUND_SETTINGS
        
    Returns:
        True if setting is enabled, False otherwise
    """
    if key not in SOUND_SETTINGS:
        log.warning(f"[SoundSettings] Unknown setting key: {key}, defaulting to True")
        return True  # Default to enabled for unknown keys to avoid silencing sounds
    
    section, option, default = SOUND_SETTINGS[key]
    
    if Settings is None:
        log.warning(f"[SoundSettings] Settings module is None, using default for {key}: {default}")
        return default == 'on'
    
    try:
        value = Settings.read(section, option, default)
        # Handle case-insensitive comparison
        result = str(value).lower() == 'on'
        log.info(f"[SoundSettings] get_sound_setting({key}): [{section}][{option}]='{value}' -> {result}")
        return result
    except Exception as e:
        log.error(f"[SoundSettings] Error reading {key}: {e}, using default={default}")
        return default == 'on'


def set_sound_setting(key: str, enabled: bool) -> bool:
    """Set a specific sound setting.
    
    Args:
        key: Setting key from SOUND_SETTINGS
        enabled: True to enable, False to disable
        
    Returns:
        True if setting was saved successfully, False otherwise
    """
    if key not in SOUND_SETTINGS:
        log.warning(f"[SoundSettings] Unknown setting key: {key}")
        return False
    
    section, option, _ = SOUND_SETTINGS[key]
    value = 'on' if enabled else 'off'
    
    if Settings is None:
        log.warning("[SoundSettings] Settings module not available, cannot save")
        return False
    
    try:
        Settings.write(section, option, value)
        log.info(f"[SoundSettings] {key} = {value}")
        return True
    except Exception as e:
        log.error(f"[SoundSettings] Failed to save {key}: {e}")
        return False


def toggle_sound_setting(key: str) -> bool:
    """Toggle a sound setting and return the new value.
    
    Args:
        key: Setting key from SOUND_SETTINGS
        
    Returns:
        New value of the setting (True if now enabled)
    """
    current = get_sound_setting(key)
    new_value = not current
    set_sound_setting(key, new_value)
    return new_value


def is_sound_enabled() -> bool:
    """Check if master sound is enabled.
    
    Returns:
        True if sound is enabled globally (defaults to True on error)
    """
    try:
        return get_sound_setting('enabled')
    except Exception as e:
        log.warning(f"[SoundSettings] Error checking master enable: {e}, defaulting to True")
        return True


def should_beep_for(event_type: str) -> bool:
    """Check if a beep should play for a given event type.
    
    Checks both the master enable and the specific event setting.
    Defaults to True (allow beep) if there are any errors reading settings.
    
    Args:
        event_type: One of 'key_press', 'error', 'game_event', 'piece_event'
        
    Returns:
        True if beep should play, False otherwise
    """
    try:
        # Master enable must be on
        master_enabled = is_sound_enabled()
        if not master_enabled:
            log.info(f"[SoundSettings] should_beep_for({event_type}): BLOCKED - master disabled")
            return False
        
        # Check specific event setting
        event_enabled = get_sound_setting(event_type)
        if event_enabled:
            log.debug(f"[SoundSettings] should_beep_for({event_type}): ALLOWED")
        else:
            log.info(f"[SoundSettings] should_beep_for({event_type}): BLOCKED - event disabled")
        return event_enabled
    except Exception as e:
        log.warning(f"[SoundSettings] Error in should_beep_for({event_type}): {e}, defaulting to True")
        return True
