"""Position loading utilities.

Provides functions for loading and parsing chess positions from configuration files.
"""

import configparser
import pathlib
from typing import Dict, Optional, Tuple


def parse_position_entry(value: str) -> Tuple[str, Optional[str]]:
    """Parse a position entry from positions.ini.
    
    Format: FEN | hint_move (hint_move is optional)
    
    Args:
        value: Raw value from INI file
        
    Returns:
        Tuple of (fen, hint_move) where hint_move may be None
    """
    if '|' in value:
        parts = value.split('|', 1)
        fen = parts[0].strip()
        hint_move = parts[1].strip() if len(parts) > 1 else None
        # Validate hint_move format (UCI: 4-5 chars like e2e4 or a7a8q)
        if hint_move and (len(hint_move) < 4 or len(hint_move) > 5):
            hint_move = None
        return (fen, hint_move)
    else:
        return (value.strip(), None)


def load_positions_config(log=None) -> Dict[str, Dict[str, Tuple[str, Optional[str]]]]:
    """Load predefined positions from positions.ini.
    
    Args:
        log: Optional logger for debug/error output
    
    Returns:
        Dictionary with category names as keys and dict of {name: (fen, hint_move)} as values.
        hint_move is None if not specified.
        Example: {'test': {'en_passant': ('fen...', 'e5d6')}, 'puzzles': {...}}
    """
    positions: Dict[str, Dict[str, Tuple[str, Optional[str]]]] = {}
    
    # Try runtime path first, then development path
    config_paths = [
        pathlib.Path("/opt/DGTCentaurMods/config/positions.ini"),
        pathlib.Path(__file__).parent.parent / "defaults" / "config" / "positions.ini"
    ]
    
    config_file = None
    for path in config_paths:
        if path.exists():
            config_file = path
            break
    
    if config_file is None:
        if log:
            log.warning("[Positions] positions.ini not found")
        return positions
    
    try:
        config = configparser.ConfigParser()
        config.read(str(config_file))
        
        for section in config.sections():
            positions[section] = {}
            for name, value in config.items(section):
                fen, hint_move = parse_position_entry(value)
                # Validate FEN has 6 fields
                if len(fen.split()) == 6:
                    positions[section][name] = (fen, hint_move)
                else:
                    if log:
                        log.warning(f"[Positions] Invalid FEN for {section}/{name}: {fen}")
        
        if log:
            log.info(f"[Positions] Loaded {sum(len(v) for v in positions.values())} positions from {len(positions)} categories")
        
    except Exception as e:
        if log:
            log.error(f"[Positions] Error loading positions.ini: {e}")
    
    return positions

