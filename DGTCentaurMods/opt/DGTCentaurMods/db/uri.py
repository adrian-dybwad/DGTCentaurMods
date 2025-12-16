"""Database URI resolution for DGTCentaurMods.

Provides the database connection URI, checking config for overrides
and falling back to the default SQLite database.
"""

import os

from DGTCentaurMods.paths import DB_DIR, DEFAULT_DB_FILE


def _normalize_sqlite_uri(db_path: str) -> str:
    """Return a SQLAlchemy sqlite URI for the provided absolute path."""
    return f"sqlite:///{db_path}"


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
            path = os.path.join(DB_DIR, path)
        return _normalize_sqlite_uri(path)

    return _normalize_sqlite_uri(DEFAULT_DB_FILE)
