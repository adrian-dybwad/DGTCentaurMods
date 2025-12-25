"""Deferred imports for game manager.

This module loads slow optional dependencies (SciPy + SQLAlchemy models) in a background
thread to reduce startup latency on constrained devices.

The public contract is via the `_get_*` accessors that block until the background
imports have completed (or timed out).
"""

import threading

from universalchess.board.logging import log

# Deferred imports - these are slow (~3s total on Raspberry Pi) and loaded in background
# to avoid blocking startup. They're only needed when a game actually starts.
_deferred_imports_ready = threading.Event()
_deferred_models = None
_deferred_linear_sum_assignment = None
_deferred_sessionmaker = None
_deferred_func = None
_deferred_select = None
_deferred_create_engine = None


def _load_deferred_imports():
    """Load slow imports in background thread.

    Imports scipy and database models which take ~3 seconds combined on Pi.
    Sets _deferred_imports_ready event when complete.

    Import order matters: scipy first (no dependencies on our code), then
    database/SQLAlchemy (which may have already been imported by db.models).
    """
    global _deferred_models, _deferred_linear_sum_assignment
    global _deferred_sessionmaker, _deferred_func, _deferred_select, _deferred_create_engine

    try:
        # Import scipy first (~1.5s) - no conflicts with our codebase
        from scipy.optimize import linear_sum_assignment as _lsa

        _deferred_linear_sum_assignment = _lsa
        log.debug("[GameManager] scipy loaded successfully")
    except Exception as e:
        log.warning(f"[GameManager] scipy import failed (correction guidance will use fallback): {e}")

    try:
        # Import database models (~1.5s)
        # Note: db.models imports SQLAlchemy at module level, so we import
        # models first to ensure SQLAlchemy is fully initialized
        from universalchess.db import models as _models

        _deferred_models = _models

        # Import SQLAlchemy components (should already be loaded by models)
        from sqlalchemy import create_engine as _create_engine, func as _func, select as _select
        from sqlalchemy.orm import sessionmaker as _sessionmaker

        _deferred_sessionmaker = _sessionmaker
        _deferred_func = _func
        _deferred_select = _select
        _deferred_create_engine = _create_engine

        log.debug("[GameManager] Deferred imports loaded successfully")
    except Exception as e:
        log.error(f"[GameManager] Error loading database imports: {e}")
    finally:
        _deferred_imports_ready.set()


# Start background import thread
_import_thread = threading.Thread(target=_load_deferred_imports, daemon=True)
_import_thread.start()


def _wait_for_imports(timeout=30.0):
    """Wait for deferred imports to complete.

    Called by functions that need the deferred modules.
    Returns True if imports are ready, False on timeout.

    Args:
        timeout: Maximum seconds to wait (default 30s, plenty of time)

    Returns:
        True if imports ready, False if timed out
    """
    if _deferred_imports_ready.is_set():
        return True
    log.debug("[GameManager] Waiting for deferred imports...")
    return _deferred_imports_ready.wait(timeout=timeout)


def _get_models():
    """Get the models module, waiting for import if needed."""
    _wait_for_imports()
    return _deferred_models


def _get_linear_sum_assignment():
    """Get the linear_sum_assignment function, waiting for import if needed."""
    _wait_for_imports()
    return _deferred_linear_sum_assignment


def _get_sessionmaker():
    """Get SQLAlchemy sessionmaker, waiting for import if needed."""
    _wait_for_imports()
    return _deferred_sessionmaker


def _get_sqlalchemy_func():
    """Get SQLAlchemy func, waiting for import if needed."""
    _wait_for_imports()
    return _deferred_func


def _get_sqlalchemy_select():
    """Get SQLAlchemy select, waiting for import if needed."""
    _wait_for_imports()
    return _deferred_select


def _get_create_engine():
    """Get SQLAlchemy create_engine, waiting for import if needed."""
    _wait_for_imports()
    return _deferred_create_engine


__all__ = [
    "_get_models",
    "_get_linear_sum_assignment",
    "_get_sessionmaker",
    "_get_sqlalchemy_func",
    "_get_sqlalchemy_select",
    "_get_create_engine",
]


