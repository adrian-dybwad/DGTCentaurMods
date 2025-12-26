"""Update checker service.

Checks GitHub releases for new versions and provides update functionality.
Uses pull-based model - the Pi checks for updates rather than being pushed to.

Features:
- Check for new stable releases
- Check for nightly builds (optional)
- Download and install updates
- Version comparison
"""

import os
import subprocess
import json
import tempfile
import threading
from pathlib import Path
from typing import Optional, Dict, Callable, List
from dataclasses import dataclass
from enum import Enum

try:
    from universalchess.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# GitHub repository info
GITHUB_OWNER = "adrian-dybwad"
GITHUB_REPO = "Universal-Chess"
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"

# Local version file (created by build.sh)
VERSION_FILE = "/opt/universalchess/VERSION"


class UpdateChannel(Enum):
    """Update channel selection."""
    STABLE = "stable"   # Only tagged releases (v*)
    NIGHTLY = "nightly" # Include nightly pre-releases


@dataclass
class ReleaseInfo:
    """Information about a GitHub release."""
    tag: str
    version: str
    name: str
    published_at: str
    is_prerelease: bool
    body: str
    download_url: Optional[str]
    download_size: int
    checksum_url: Optional[str]


class UpdateChecker:
    """Service for checking and applying updates."""
    
    def __init__(self, channel: UpdateChannel = UpdateChannel.STABLE):
        """Initialize the update checker.
        
        Args:
            channel: Update channel (STABLE or NIGHTLY)
        """
        self.channel = channel
        self._current_version: Optional[str] = None
        self._latest_release: Optional[ReleaseInfo] = None
        self._checking = False
        self._downloading = False
        self._download_progress = 0
        self._error: Optional[str] = None
        self._listeners: List[Callable[[str, str], None]] = []
        
        log.info(f"[UpdateChecker] Initialized with channel={channel.value}")
    
    def add_listener(self, callback: Callable[[str, str], None]) -> None:
        """Add a listener for update events.
        
        Args:
            callback: Function called with (event_type, message)
                      event_type: "checking", "available", "current", "downloading", 
                                  "installing", "complete", "error"
        """
        self._listeners.append(callback)
    
    def remove_listener(self, callback: Callable[[str, str], None]) -> None:
        """Remove an update listener."""
        if callback in self._listeners:
            self._listeners.remove(callback)
    
    def _notify(self, event_type: str, message: str) -> None:
        """Notify all listeners of an event."""
        for listener in self._listeners:
            try:
                listener(event_type, message)
            except Exception as e:
                log.error(f"[UpdateChecker] Listener error: {e}")
    
    def get_current_version(self) -> str:
        """Get the currently installed version.
        
        Returns:
            Version string (e.g., "1.3.3")
        """
        if self._current_version:
            return self._current_version
        
        # Try VERSION file first
        if os.path.exists(VERSION_FILE):
            try:
                with open(VERSION_FILE, 'r') as f:
                    self._current_version = f.read().strip()
                    log.debug(f"[UpdateChecker] Version from file: {self._current_version}")
                    return self._current_version
            except Exception as e:
                log.warning(f"[UpdateChecker] Could not read VERSION file: {e}")
        
        # Fallback: try to get from dpkg
        try:
            result = subprocess.run(
                ["dpkg-query", "-W", "-f=${Version}", "universal-chess"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                self._current_version = result.stdout.strip()
                log.debug(f"[UpdateChecker] Version from dpkg: {self._current_version}")
                return self._current_version
        except Exception as e:
            log.warning(f"[UpdateChecker] Could not get version from dpkg: {e}")
        
        # Fallback: unknown
        self._current_version = "unknown"
        return self._current_version
    
    def check_for_updates(self) -> Optional[ReleaseInfo]:
        """Check GitHub for new releases.
        
        Returns:
            ReleaseInfo if update available, None if current
        """
        if self._checking:
            log.warning("[UpdateChecker] Already checking for updates")
            return None
        
        self._checking = True
        self._error = None
        self._notify("checking", "Checking for updates...")
        
        try:
            releases = self._fetch_releases()
            if not releases:
                self._notify("error", "Could not fetch releases")
                return None
            
            # Find the latest applicable release
            current = self.get_current_version()
            log.info(f"[UpdateChecker] Current version: {current}")
            
            for release in releases:
                # Skip prereleases if on stable channel
                if self.channel == UpdateChannel.STABLE and release.is_prerelease:
                    continue
                
                # Compare versions
                if self._is_newer(release.version, current):
                    self._latest_release = release
                    log.info(f"[UpdateChecker] Update available: {release.version}")
                    self._notify("available", f"Update available: v{release.version}")
                    return release
            
            log.info("[UpdateChecker] Already up to date")
            self._notify("current", f"Up to date (v{current})")
            return None
            
        except Exception as e:
            self._error = str(e)
            log.error(f"[UpdateChecker] Error checking for updates: {e}")
            self._notify("error", f"Error: {e}")
            return None
        finally:
            self._checking = False
    
    def _fetch_releases(self) -> List[ReleaseInfo]:
        """Fetch releases from GitHub API.
        
        Returns:
            List of ReleaseInfo objects
        """
        url = f"{GITHUB_API_BASE}/releases"
        log.debug(f"[UpdateChecker] Fetching releases from {url}")
        
        try:
            # Use curl for simplicity (available on all Pi systems)
            result = subprocess.run(
                ["curl", "-s", "-H", "Accept: application/vnd.github+json", url],
                capture_output=True, text=True, timeout=30
            )
            
            if result.returncode != 0:
                log.error(f"[UpdateChecker] curl failed: {result.stderr}")
                return []
            
            data = json.loads(result.stdout)
            
            if isinstance(data, dict) and "message" in data:
                log.error(f"[UpdateChecker] GitHub API error: {data['message']}")
                return []
            
            releases = []
            for item in data[:10]:  # Only check last 10 releases
                # Find .deb asset
                deb_asset = None
                checksum_asset = None
                for asset in item.get("assets", []):
                    name = asset.get("name", "")
                    if name.endswith(".deb"):
                        deb_asset = asset
                    elif name == "SHA256SUMS.txt":
                        checksum_asset = asset
                
                tag = item.get("tag_name", "")
                version = tag.lstrip("v") if tag.startswith("v") else tag
                
                releases.append(ReleaseInfo(
                    tag=tag,
                    version=version,
                    name=item.get("name", tag),
                    published_at=item.get("published_at", ""),
                    is_prerelease=item.get("prerelease", False),
                    body=item.get("body", "")[:500],  # Truncate
                    download_url=deb_asset.get("browser_download_url") if deb_asset else None,
                    download_size=deb_asset.get("size", 0) if deb_asset else 0,
                    checksum_url=checksum_asset.get("browser_download_url") if checksum_asset else None,
                ))
            
            log.info(f"[UpdateChecker] Found {len(releases)} releases")
            return releases
            
        except json.JSONDecodeError as e:
            log.error(f"[UpdateChecker] JSON parse error: {e}")
            return []
        except Exception as e:
            log.error(f"[UpdateChecker] Fetch error: {e}")
            return []
    
    def _is_newer(self, new_version: str, current_version: str) -> bool:
        """Compare version strings.
        
        Args:
            new_version: Version to check
            current_version: Current installed version
            
        Returns:
            True if new_version > current_version
        """
        if current_version == "unknown":
            return True
        
        try:
            # Handle nightly versions like "1.3.3-nightly.20251225.abc1234"
            def parse_version(v: str) -> tuple:
                # Split on hyphen to separate base version from suffix
                parts = v.split("-", 1)
                base = parts[0]
                suffix = parts[1] if len(parts) > 1 else ""
                
                # Parse base version (e.g., "1.3.3" -> (1, 3, 3))
                base_parts = tuple(int(x) for x in base.split(".") if x.isdigit())
                
                # Nightly versions are considered "newer" than same base stable
                is_nightly = "nightly" in suffix
                
                return (base_parts, is_nightly, suffix)
            
            new_parsed = parse_version(new_version)
            current_parsed = parse_version(current_version)
            
            # Compare base versions first
            if new_parsed[0] > current_parsed[0]:
                return True
            elif new_parsed[0] < current_parsed[0]:
                return False
            
            # Same base version - nightly is newer than stable
            if new_parsed[1] and not current_parsed[1]:
                return True
            
            # Both nightly or both stable with same base - compare suffixes
            if new_parsed[1] and current_parsed[1]:
                return new_parsed[2] > current_parsed[2]
            
            return False
            
        except Exception as e:
            log.warning(f"[UpdateChecker] Version comparison error: {e}")
            return False
    
    def download_update(self, release: Optional[ReleaseInfo] = None) -> Optional[Path]:
        """Download an update package.
        
        Args:
            release: Release to download (uses latest if None)
            
        Returns:
            Path to downloaded .deb file, or None on failure
        """
        release = release or self._latest_release
        if not release:
            log.error("[UpdateChecker] No release to download")
            return None
        
        if not release.download_url:
            log.error(f"[UpdateChecker] No download URL for {release.version}")
            self._notify("error", "No download available")
            return None
        
        self._downloading = True
        self._download_progress = 0
        self._notify("downloading", f"Downloading v{release.version}...")
        
        try:
            # Download to temp directory
            tmp_dir = tempfile.mkdtemp(prefix="uc-update-")
            deb_path = Path(tmp_dir) / f"universal-chess_{release.version}_all.deb"
            
            log.info(f"[UpdateChecker] Downloading {release.download_url} to {deb_path}")
            
            # Use wget with progress
            result = subprocess.run(
                ["wget", "-q", "-O", str(deb_path), release.download_url],
                capture_output=True, text=True, timeout=600  # 10 min timeout
            )
            
            if result.returncode != 0:
                log.error(f"[UpdateChecker] Download failed: {result.stderr}")
                self._notify("error", "Download failed")
                return None
            
            if not deb_path.exists():
                log.error("[UpdateChecker] Downloaded file not found")
                self._notify("error", "Download failed")
                return None
            
            log.info(f"[UpdateChecker] Downloaded {deb_path.stat().st_size} bytes")
            self._notify("downloading", "Download complete")
            return deb_path
            
        except subprocess.TimeoutExpired:
            log.error("[UpdateChecker] Download timed out")
            self._notify("error", "Download timed out")
            return None
        except Exception as e:
            log.error(f"[UpdateChecker] Download error: {e}")
            self._notify("error", f"Download error: {e}")
            return None
        finally:
            self._downloading = False
    
    def install_update(self, deb_path: Path) -> bool:
        """Install a downloaded update.
        
        Args:
            deb_path: Path to .deb file
            
        Returns:
            True if installation succeeded
        """
        if not deb_path.exists():
            log.error(f"[UpdateChecker] .deb file not found: {deb_path}")
            return False
        
        self._notify("installing", "Installing update...")
        
        try:
            log.info(f"[UpdateChecker] Installing {deb_path}")
            
            # Install with dpkg
            result = subprocess.run(
                ["sudo", "dpkg", "-i", str(deb_path)],
                capture_output=True, text=True, timeout=300
            )
            
            if result.returncode != 0:
                # Try to fix dependencies
                log.warning("[UpdateChecker] dpkg failed, trying apt-get -f install")
                subprocess.run(
                    ["sudo", "apt-get", "install", "-f", "-y"],
                    capture_output=True, text=True, timeout=300
                )
                
                # Retry dpkg
                result = subprocess.run(
                    ["sudo", "dpkg", "-i", str(deb_path)],
                    capture_output=True, text=True, timeout=300
                )
                
                if result.returncode != 0:
                    log.error(f"[UpdateChecker] Install failed: {result.stderr}")
                    self._notify("error", "Installation failed")
                    return False
            
            log.info("[UpdateChecker] Installation complete")
            self._notify("complete", "Update installed. Restart required.")
            
            # Clear cached version
            self._current_version = None
            
            return True
            
        except subprocess.TimeoutExpired:
            log.error("[UpdateChecker] Install timed out")
            self._notify("error", "Installation timed out")
            return False
        except Exception as e:
            log.error(f"[UpdateChecker] Install error: {e}")
            self._notify("error", f"Install error: {e}")
            return False
    
    def check_and_update_async(
        self,
        auto_install: bool = False,
        callback: Optional[Callable[[bool], None]] = None
    ) -> None:
        """Check for updates and optionally install in background.
        
        Args:
            auto_install: If True, automatically install if update found
            callback: Called with success status when complete
        """
        def _worker():
            try:
                release = self.check_for_updates()
                if not release:
                    if callback:
                        callback(False)
                    return
                
                if auto_install:
                    deb_path = self.download_update(release)
                    if deb_path:
                        success = self.install_update(deb_path)
                        if callback:
                            callback(success)
                    else:
                        if callback:
                            callback(False)
                else:
                    if callback:
                        callback(True)  # Update available
                        
            except Exception as e:
                log.error(f"[UpdateChecker] Async update error: {e}")
                if callback:
                    callback(False)
        
        thread = threading.Thread(target=_worker, name="update-checker", daemon=True)
        thread.start()
    
    def get_latest_release(self) -> Optional[ReleaseInfo]:
        """Get the cached latest release info."""
        return self._latest_release
    
    def is_checking(self) -> bool:
        """Check if currently checking for updates."""
        return self._checking
    
    def is_downloading(self) -> bool:
        """Check if currently downloading an update."""
        return self._downloading
    
    def get_error(self) -> Optional[str]:
        """Get the last error message."""
        return self._error


# Module-level singleton
_update_checker: Optional[UpdateChecker] = None


def get_update_checker(channel: UpdateChannel = UpdateChannel.STABLE) -> UpdateChecker:
    """Get the update checker singleton."""
    global _update_checker
    if _update_checker is None:
        _update_checker = UpdateChecker(channel)
    return _update_checker

