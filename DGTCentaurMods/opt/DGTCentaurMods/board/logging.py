# Logging configuration for DGTCentaurMods
#
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

import logging
import sys


class ColoredFormatter(logging.Formatter):
    """Formatter that adds colors to log levels for console output."""
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_colors = sys.stdout.isatty()
    
    def format(self, record):
        if self.use_colors:
            original_levelname = record.levelname
            # Pad to 8 characters before adding color codes
            padded_levelname = f"{original_levelname:<8}"
            color = self.COLORS.get(original_levelname, '')
            record.levelname = f"{color}{padded_levelname}{self.RESET}"
            result = super().format(record)
            record.levelname = original_levelname
            return result
        return super().format(record)


def setup_logging(log_file_path="/home/pi/debug.log", log_level=logging.DEBUG):
    """Configure logging with colored console output and file output.
    
    Args:
        log_file_path: Path to the log file. If None, file logging is skipped.
        log_level: Logging level to set (default: logging.DEBUG).
    
    Returns:
        The configured logger instance.
    """
    log = logging.getLogger()
    log.setLevel(log_level)
    log.handlers = []
    
    # File handler with plain formatter
    _fmt = logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s", "%Y-%m-%d %H:%M:%S")
    
    if log_file_path:
        try:
            _fh = logging.FileHandler(log_file_path, mode="w")
            _fh.setLevel(log_level)
            _fh.setFormatter(_fmt)
            log.addHandler(_fh)
        except Exception:
            pass
    
    # Console handler with colored formatter
    _ch = logging.StreamHandler(sys.stdout)
    _ch.setLevel(log_level)
    _ch.setFormatter(ColoredFormatter("%(asctime)s.%(msecs)03d %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(_ch)
    
    return log


# Automatically configure and export log on module import
log = setup_logging()

