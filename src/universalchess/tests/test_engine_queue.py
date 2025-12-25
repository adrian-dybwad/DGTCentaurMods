"""Tests for EngineManager install queue functionality.

Tests queue operations, progress callbacks, and queue state management.
Does not test actual installation (that requires hardware/network).
"""

import pytest
import threading
import time
from unittest.mock import MagicMock, patch

from universalchess.managers.engine_manager import (
    EngineManager,
    InstallStatus,
    QueuedEngine,
    ENGINES,
)


@pytest.fixture
def engine_manager(tmp_path):
    """Create an EngineManager with temp directories."""
    engines_dir = tmp_path / "engines"
    engines_dir.mkdir()
    manager = EngineManager(engines_dir=str(engines_dir))
    manager.build_tmp = tmp_path / "build"
    manager.build_tmp.mkdir()
    return manager


class TestQueueBasics:
    """Basic queue operations."""
    
    def test_queue_engine_adds_to_queue(self, engine_manager):
        """Queuing an engine adds it to the queue.
        
        Expected: queue_engine returns True and engine appears in queue/history.
        Why: Basic queue functionality must work.
        """
        # Patch install_engine to avoid actual install and prevent worker from starting
        with patch.object(engine_manager, '_start_queue_worker'):
            result = engine_manager.queue_engine("ct800")
        
        assert result is True
        status = engine_manager.get_queue_status()
        assert len(status) >= 1
        assert any(s["name"] == "ct800" for s in status)
    
    def test_queue_unknown_engine_fails(self, engine_manager):
        """Queuing unknown engine returns False.
        
        Expected: queue_engine returns False for non-existent engine.
        Why: Should validate engine names before queueing.
        """
        result = engine_manager.queue_engine("nonexistent_engine")
        assert result is False
    
    def test_queue_duplicate_fails(self, engine_manager):
        """Queuing same engine twice fails.
        
        Expected: Second queue_engine call returns False.
        Why: Should not allow duplicate queue entries.
        """
        # Prevent worker from processing so we can test duplicate detection
        with patch.object(engine_manager, '_start_queue_worker'):
            result1 = engine_manager.queue_engine("ct800")
            result2 = engine_manager.queue_engine("ct800")
        
        assert result1 is True
        assert result2 is False
    
    def test_queue_installed_engine_fails(self, engine_manager, tmp_path):
        """Queuing already-installed engine returns False.
        
        Expected: queue_engine returns False if engine is already installed.
        Why: No need to reinstall existing engines.
        """
        # Create fake installed engine
        (engine_manager.engines_dir / "ct800").touch()
        (engine_manager.engines_dir / "ct800").chmod(0o755)
        
        result = engine_manager.queue_engine("ct800")
        assert result is False


class TestQueueMultiple:
    """Multi-engine queue operations."""
    
    def test_queue_engines_multiple(self, engine_manager):
        """Queue multiple engines at once.
        
        Expected: queue_engines returns count of successfully queued.
        Why: Bulk queue operation for convenience.
        """
        # Prevent worker from processing so we can check queue
        with patch.object(engine_manager, '_start_queue_worker'):
            count = engine_manager.queue_engines(["ct800", "zahak", "demolito"])
        
        assert count == 3
        status = engine_manager.get_queue_status()
        assert len(status) >= 3
    
    def test_queue_recommended(self, engine_manager):
        """Queue recommended engines.
        
        Expected: queue_recommended queues the recommended set.
        Why: Convenience for fresh installs.
        """
        with patch.object(engine_manager, '_start_queue_worker'):
            count = engine_manager.queue_recommended()
        
        assert count >= 2  # At least some should be queued


class TestQueueCancel:
    """Queue cancellation operations."""
    
    def test_cancel_queued_engine(self, engine_manager):
        """Cancel a queued engine.
        
        Expected: cancel_queued returns True and engine status is cancelled.
        Why: Users should be able to cancel pending installs.
        """
        # Add to queue but don't start worker
        with patch.object(engine_manager, '_start_queue_worker'):
            engine_manager.queue_engine("ct800")
        
        result = engine_manager.cancel_queued("ct800")
        assert result is True
        
        # Should not appear in active queue
        status = engine_manager.get_queue_status()
        assert not any(s["name"] == "ct800" for s in status)
    
    def test_cancel_nonexistent_fails(self, engine_manager):
        """Cancelling non-queued engine returns False.
        
        Expected: cancel_queued returns False for engine not in queue.
        Why: Should handle missing items gracefully.
        """
        result = engine_manager.cancel_queued("ct800")
        assert result is False
    
    def test_clear_queue(self, engine_manager):
        """Clear all queued engines.
        
        Expected: clear_queue cancels all pending items.
        Why: Users should be able to clear entire queue.
        """
        with patch.object(engine_manager, '_start_queue_worker'):
            engine_manager.queue_engines(["ct800", "zahak", "demolito"])
        
        count = engine_manager.clear_queue()
        assert count == 3
        
        status = engine_manager.get_queue_status()
        assert len(status) == 0


class TestProgressCallbacks:
    """Progress callback functionality."""
    
    def test_add_progress_listener(self, engine_manager):
        """Add a progress listener.
        
        Expected: Listener is called with progress updates.
        Why: UI needs to receive progress events.
        """
        events = []
        
        def listener(name, status, msg):
            events.append((name, status, msg))
        
        engine_manager.add_progress_listener(listener)
        
        with patch.object(engine_manager, '_start_queue_worker'):
            engine_manager.queue_engine("ct800")
        
        assert len(events) >= 1
        assert events[0][0] == "ct800"
        assert events[0][1] == "queued"
    
    def test_remove_progress_listener(self, engine_manager):
        """Remove a progress listener.
        
        Expected: Removed listener no longer receives events.
        Why: Cleanup prevents memory leaks and stale callbacks.
        """
        events = []
        
        def listener(name, status, msg):
            events.append((name, status, msg))
        
        engine_manager.add_progress_listener(listener)
        engine_manager.remove_progress_listener(listener)
        
        with patch.object(engine_manager, '_start_queue_worker'):
            engine_manager.queue_engine("ct800")
        
        assert len(events) == 0


class TestQueueHistory:
    """Queue history functionality."""
    
    def test_get_queue_history_empty(self, engine_manager):
        """Empty history returns empty list.
        
        Expected: get_queue_history returns [] when nothing completed.
        Why: Should handle empty state gracefully.
        """
        history = engine_manager.get_queue_history()
        assert history == []
    
    def test_queue_status_format(self, engine_manager):
        """Queue status has expected fields.
        
        Expected: Each item has name, display_name, status, progress, etc.
        Why: UI depends on consistent format.
        """
        with patch.object(engine_manager, '_start_queue_worker'):
            engine_manager.queue_engine("ct800")
        
        status = engine_manager.get_queue_status()
        assert len(status) >= 1
        
        item = status[0]
        assert "name" in item
        assert "display_name" in item
        assert "status" in item
        assert "progress" in item
        assert "estimated_minutes" in item

