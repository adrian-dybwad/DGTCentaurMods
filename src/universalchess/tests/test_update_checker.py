"""Tests for UpdateChecker service.

Tests version comparison and event handling.
Does not test actual network calls (mocked).
"""

import pytest
from unittest.mock import MagicMock, patch

from universalchess.services.update_checker import (
    UpdateChecker,
    UpdateChannel,
    ReleaseInfo,
)


@pytest.fixture
def update_checker():
    """Create an UpdateChecker instance."""
    return UpdateChecker(channel=UpdateChannel.STABLE)


class TestVersionComparison:
    """Tests for version comparison logic."""
    
    def test_newer_major_version(self, update_checker):
        """Major version bump is detected as newer.
        
        Expected: 2.0.0 > 1.3.3
        Why: Major version changes should trigger updates.
        """
        assert update_checker._is_newer("2.0.0", "1.3.3") is True
    
    def test_newer_minor_version(self, update_checker):
        """Minor version bump is detected as newer.
        
        Expected: 1.4.0 > 1.3.3
        Why: Minor version changes should trigger updates.
        """
        assert update_checker._is_newer("1.4.0", "1.3.3") is True
    
    def test_newer_patch_version(self, update_checker):
        """Patch version bump is detected as newer.
        
        Expected: 1.3.4 > 1.3.3
        Why: Patch version changes should trigger updates.
        """
        assert update_checker._is_newer("1.3.4", "1.3.3") is True
    
    def test_same_version_not_newer(self, update_checker):
        """Same version is not newer.
        
        Expected: 1.3.3 is not > 1.3.3
        Why: Should not offer update for same version.
        """
        assert update_checker._is_newer("1.3.3", "1.3.3") is False
    
    def test_older_version_not_newer(self, update_checker):
        """Older version is not newer.
        
        Expected: 1.3.2 is not > 1.3.3
        Why: Should not downgrade.
        """
        assert update_checker._is_newer("1.3.2", "1.3.3") is False
    
    def test_unknown_version_triggers_update(self, update_checker):
        """Unknown current version should accept any update.
        
        Expected: Any version > "unknown"
        Why: Fresh installs or corrupt version should update.
        """
        assert update_checker._is_newer("1.0.0", "unknown") is True
    
    def test_nightly_newer_than_same_stable(self, update_checker):
        """Nightly is newer than same base stable version.
        
        Expected: 1.3.3-nightly.xxx > 1.3.3
        Why: Nightly builds on same base should be considered newer.
        """
        assert update_checker._is_newer("1.3.3-nightly.20251225", "1.3.3") is True
    
    def test_nightly_comparison(self, update_checker):
        """Newer nightly is detected.
        
        Expected: 1.3.3-nightly.20251226 > 1.3.3-nightly.20251225
        Why: Later nightly dates should be newer.
        """
        assert update_checker._is_newer("1.3.3-nightly.20251226", "1.3.3-nightly.20251225") is True


class TestEventListeners:
    """Tests for event listener functionality."""
    
    def test_add_listener(self, update_checker):
        """Add a listener receives events.
        
        Expected: Listener callback is called on events.
        Why: UI needs to receive update notifications.
        """
        events = []
        
        def listener(event_type, message):
            events.append((event_type, message))
        
        update_checker.add_listener(listener)
        update_checker._notify("checking", "Test message")
        
        assert len(events) == 1
        assert events[0] == ("checking", "Test message")
    
    def test_remove_listener(self, update_checker):
        """Removed listener stops receiving events.
        
        Expected: After removal, listener not called.
        Why: Cleanup should work properly.
        """
        events = []
        
        def listener(event_type, message):
            events.append((event_type, message))
        
        update_checker.add_listener(listener)
        update_checker.remove_listener(listener)
        update_checker._notify("checking", "Test message")
        
        assert len(events) == 0


class TestCurrentVersion:
    """Tests for version detection."""
    
    def test_caches_version(self, update_checker):
        """Version is cached after first retrieval.
        
        Expected: Second call uses cached value.
        Why: Avoid repeated file/dpkg calls.
        """
        update_checker._current_version = "1.2.3"
        
        result = update_checker.get_current_version()
        
        assert result == "1.2.3"
    
    def test_unknown_fallback(self, update_checker):
        """Falls back to 'unknown' if version cannot be determined.
        
        Expected: Returns 'unknown' when no version sources available.
        Why: Graceful degradation.
        """
        # Mock no VERSION file and failed dpkg
        with patch('os.path.exists', return_value=False):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value.returncode = 1
                mock_run.return_value.stdout = ""
                
                result = update_checker.get_current_version()
        
        assert result == "unknown"


class TestReleaseInfo:
    """Tests for ReleaseInfo dataclass."""
    
    def test_release_info_fields(self):
        """ReleaseInfo has all expected fields.
        
        Expected: All fields are accessible.
        Why: Ensure dataclass is properly defined.
        """
        release = ReleaseInfo(
            tag="v1.3.4",
            version="1.3.4",
            name="Version 1.3.4",
            published_at="2025-12-25T00:00:00Z",
            is_prerelease=False,
            body="Release notes",
            download_url="https://example.com/file.deb",
            download_size=1024,
            checksum_url="https://example.com/SHA256SUMS.txt",
        )
        
        assert release.tag == "v1.3.4"
        assert release.version == "1.3.4"
        assert release.is_prerelease is False
        assert release.download_size == 1024

