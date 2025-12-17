"""Engine Manager - Install and manage UCI chess engines.

Provides functionality to:
- List available engines with installation status
- Install engines from source (compile on device)
- Uninstall engines
- Check if engines are installed

Supported engines (14 total):

Top Tier (~3300+ ELO):
- stockfish: World's strongest, installed from system package
- berserk: Top-3 ranked, NNUE-based
- koivisto: Top-10, fast and aggressive
- ethereal: Top-15, clean codebase

Strong Tier (~2900-3200 ELO):
- fire: Optimized for modern CPUs
- laser: Fast tactical search
- demolito: Simple and efficient
- weiss: Clean, educational
- arasan: Veteran engine since 1994
- smallbrain: Compact NNUE engine

Specialty Engines:
- rodentIV: 50+ playing personalities
- ct800: Classic chess computer style
- maia: Human-like play (makes mistakes)
- zahak: Go-based, fast development
"""

import os
import subprocess
import shutil
import threading
from dataclasses import dataclass
from typing import Optional, Callable, List
from pathlib import Path

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

# Engine installation directory
ENGINES_DIR = "/opt/DGTCentaurMods/engines"
BUILD_TMP = "/opt/DGTCentaurMods/tmp/engine_build"


@dataclass
class EngineDefinition:
    """Definition of a chess engine that can be installed."""
    name: str                    # Engine name (used as executable name)
    display_name: str            # Human-readable name for UI
    description: str             # Short description
    repo_url: Optional[str]      # Git repository URL (None for system package)
    build_commands: List[str]    # Commands to build after cloning
    binary_path: str             # Path to binary after build (relative to repo)
    is_system_package: bool      # True if installed via apt
    package_name: Optional[str]  # apt package name (if system package)
    extra_files: List[str]       # Additional files/dirs to copy (relative to repo)
    dependencies: List[str]      # apt packages needed to build


# Engine definitions
# Ordered roughly by strength/popularity
ENGINES = {
    # === TOP TIER - World class engines ===
    "stockfish": EngineDefinition(
        name="stockfish",
        display_name="Stockfish",
        description="World's strongest open-source engine. NNUE-based, ~3500 ELO. The gold standard.",
        repo_url=None,
        build_commands=[],
        binary_path="",
        is_system_package=True,
        package_name="stockfish",
        extra_files=[],
        dependencies=[],
    ),
    "berserk": EngineDefinition(
        name="berserk",
        display_name="Berserk",
        description="Top-3 ranked engine. NNUE-based, ~3400 ELO. Very strong tactical play.",
        repo_url="https://github.com/jhonnold/berserk.git",
        build_commands=[
            "make -j$(nproc) EXE=berserk",
        ],
        binary_path="berserk",
        is_system_package=False,
        package_name=None,
        extra_files=[],
        dependencies=["build-essential", "git"],
    ),
    "koivisto": EngineDefinition(
        name="koivisto",
        display_name="Koivisto",
        description="Top-10 engine with NNUE. ~3350 ELO. Fast and aggressive style.",
        repo_url="https://github.com/Luecx/Koivisto.git",
        build_commands=[
            "make -j$(nproc) EXE=koivisto",
        ],
        binary_path="koivisto",
        is_system_package=False,
        package_name=None,
        extra_files=[],
        dependencies=["build-essential", "git"],
    ),
    "ethereal": EngineDefinition(
        name="ethereal",
        display_name="Ethereal",
        description="Top-15 engine. NNUE-based, ~3300 ELO. Clean, well-documented code.",
        repo_url="https://github.com/AndyGrant/Ethereal.git",
        build_commands=[
            "make -j$(nproc) EXE=ethereal",
        ],
        binary_path="ethereal",
        is_system_package=False,
        package_name=None,
        extra_files=[],
        dependencies=["build-essential", "git"],
    ),
    
    # === STRONG TIER - Tournament-level engines ===
    "fire": EngineDefinition(
        name="fire",
        display_name="Fire",
        description="Strong C++ engine. ~3200 ELO. Optimized for speed and modern CPUs.",
        repo_url="https://github.com/FireFather/fire.git",
        build_commands=[
            "make -j$(nproc) EXE=fire",
        ],
        binary_path="fire",
        is_system_package=False,
        package_name=None,
        extra_files=[],
        dependencies=["build-essential", "git"],
    ),
    "laser": EngineDefinition(
        name="laser",
        display_name="Laser",
        description="Fast tactical engine. ~3100 ELO. Known for quick search speed.",
        repo_url="https://github.com/jeffreyan11/laser-chess-engine.git",
        build_commands=[
            "make -j$(nproc)",
        ],
        binary_path="laser",
        is_system_package=False,
        package_name=None,
        extra_files=[],
        dependencies=["build-essential", "git"],
    ),
    "demolito": EngineDefinition(
        name="demolito",
        display_name="Demolito",
        description="Simple, efficient engine. ~2900 ELO. Clean C code, fast compile.",
        repo_url="https://github.com/lucasart/Demolito.git",
        build_commands=[
            "make -j$(nproc)",
        ],
        binary_path="demolito",
        is_system_package=False,
        package_name=None,
        extra_files=[],
        dependencies=["build-essential", "git"],
    ),
    "weiss": EngineDefinition(
        name="weiss",
        display_name="Weiss",
        description="Clean, educational engine. ~2900 ELO. Great for learning chess programming.",
        repo_url="https://github.com/TerjeKir/weiss.git",
        build_commands=[
            "make -j$(nproc) EXE=weiss",
        ],
        binary_path="weiss",
        is_system_package=False,
        package_name=None,
        extra_files=[],
        dependencies=["build-essential", "git"],
    ),
    "arasan": EngineDefinition(
        name="arasan",
        display_name="Arasan",
        description="Veteran engine since 1994. ~2900 ELO. NNUE support, very stable.",
        repo_url="https://github.com/jdart1/arasan-chess.git",
        build_commands=[
            "cd src && make -j$(nproc)",
        ],
        binary_path="src/arasan",
        is_system_package=False,
        package_name=None,
        extra_files=[],
        dependencies=["build-essential", "git"],
    ),
    
    # === SPECIALTY ENGINES ===
    "rodentIV": EngineDefinition(
        name="rodentIV",
        display_name="Rodent IV",
        description="Personality engine. ~2800 ELO. 50+ playing styles from beginner to GM.",
        repo_url="https://github.com/nescitus/rodent-iv.git",
        build_commands=[
            "make -j$(nproc)",
        ],
        binary_path="rodentIV",
        is_system_package=False,
        package_name=None,
        extra_files=["personalities", "books"],
        dependencies=["build-essential", "git"],
    ),
    "ct800": EngineDefinition(
        name="ct800",
        display_name="CT800",
        description="Dedicated chess computer. ~2300 ELO. Emulates classic chess computer style.",
        repo_url="https://github.com/bcm314/CT800.git",
        build_commands=[
            "cd src/application/uci && make -j$(nproc)",
        ],
        binary_path="src/application/uci/CT800_V1.43",
        is_system_package=False,
        package_name=None,
        extra_files=[],
        dependencies=["build-essential", "git"],
    ),
    "maia": EngineDefinition(
        name="maia",
        display_name="Maia",
        description="Human-like engine. Trained on human games. Makes human-like mistakes.",
        repo_url="https://github.com/CSSLab/maia-chess.git",
        build_commands=[
            # Maia uses lc0 backend - download weights only
            "echo 'Downloading Maia weights...'",
        ],
        binary_path="lc0",
        is_system_package=False,
        package_name=None,
        extra_files=["maia_weights"],
        dependencies=["build-essential", "git", "meson", "ninja-build"],
    ),
    
    # === LIGHTWEIGHT/FAST COMPILE ===
    "zahak": EngineDefinition(
        name="zahak",
        display_name="Zahak",
        description="Go-based engine. ~2700 ELO. Fast development, clean code.",
        repo_url="https://github.com/amanjpro/zahak.git",
        build_commands=[
            "go build -o zahak",
        ],
        binary_path="zahak",
        is_system_package=False,
        package_name=None,
        extra_files=[],
        dependencies=["golang-go", "git"],
    ),
    "smallbrain": EngineDefinition(
        name="smallbrain",
        display_name="Smallbrain",
        description="Compact NNUE engine. ~3000 ELO. Small binary, efficient code.",
        repo_url="https://github.com/Disservin/Smallbrain.git",
        build_commands=[
            "make -j$(nproc) EXE=smallbrain",
        ],
        binary_path="smallbrain",
        is_system_package=False,
        package_name=None,
        extra_files=[],
        dependencies=["build-essential", "git"],
    ),
}


class EngineManager:
    """Manages installation and removal of chess engines."""
    
    def __init__(self, engines_dir: str = ENGINES_DIR):
        """Initialize the engine manager.
        
        Args:
            engines_dir: Directory where engines are installed
        """
        self.engines_dir = Path(engines_dir)
        self.build_tmp = Path(BUILD_TMP)
        self._install_thread: Optional[threading.Thread] = None
        self._install_progress: str = ""
        self._install_error: Optional[str] = None
    
    def is_installed(self, engine_name: str) -> bool:
        """Check if an engine is installed.
        
        Args:
            engine_name: Name of the engine to check
            
        Returns:
            True if the engine executable exists
        """
        if engine_name not in ENGINES:
            return False
        
        engine = ENGINES[engine_name]
        
        if engine.is_system_package:
            # Check if system command exists
            return shutil.which(engine_name) is not None
        else:
            # Check if binary exists in engines directory
            engine_path = self.engines_dir / engine_name
            return engine_path.exists() and os.access(engine_path, os.X_OK)
    
    def get_engine_list(self) -> List[dict]:
        """Get list of all engines with installation status.
        
        Returns:
            List of dicts with engine info and installed status
        """
        result = []
        for name, engine in ENGINES.items():
            result.append({
                "name": name,
                "display_name": engine.display_name,
                "description": engine.description,
                "installed": self.is_installed(name),
                "is_system_package": engine.is_system_package,
            })
        return result
    
    def install_engine(
        self,
        engine_name: str,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> bool:
        """Install an engine.
        
        For system packages, uses apt-get.
        For source engines, clones repo and builds.
        
        Args:
            engine_name: Name of the engine to install
            progress_callback: Optional callback for progress updates
            
        Returns:
            True if installation succeeded
        """
        if engine_name not in ENGINES:
            log.error(f"[EngineManager] Unknown engine: {engine_name}")
            return False
        
        engine = ENGINES[engine_name]
        
        def update_progress(msg: str):
            self._install_progress = msg
            log.info(f"[EngineManager] {msg}")
            if progress_callback:
                progress_callback(msg)
        
        try:
            if engine.is_system_package:
                return self._install_system_package(engine, update_progress)
            else:
                return self._install_from_source(engine, update_progress)
        except Exception as e:
            self._install_error = str(e)
            log.error(f"[EngineManager] Install failed: {e}")
            return False
    
    def _install_system_package(
        self,
        engine: EngineDefinition,
        update_progress: Callable[[str], None]
    ) -> bool:
        """Install engine from system package."""
        update_progress(f"Installing {engine.display_name} from system package...")
        
        # Update package list
        result = subprocess.run(
            ["sudo", "apt-get", "update", "-qq"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            log.warning(f"[EngineManager] apt update warning: {result.stderr}")
        
        # Install package
        update_progress(f"Installing {engine.package_name}...")
        result = subprocess.run(
            ["sudo", "apt-get", "install", "-y", engine.package_name],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            self._install_error = result.stderr
            return False
        
        # Create symlink in engines directory
        system_path = shutil.which(engine.name)
        if system_path:
            link_path = self.engines_dir / engine.name
            link_path.unlink(missing_ok=True)
            link_path.symlink_to(system_path)
            update_progress(f"Created symlink: {link_path} -> {system_path}")
        
        update_progress(f"{engine.display_name} installed successfully")
        return True
    
    def _install_from_source(
        self,
        engine: EngineDefinition,
        update_progress: Callable[[str], None]
    ) -> bool:
        """Install engine by building from source."""
        # Ensure build directory exists
        self.build_tmp.mkdir(parents=True, exist_ok=True)
        repo_dir = self.build_tmp / engine.name
        
        # Install build dependencies
        if engine.dependencies:
            update_progress(f"Installing build dependencies...")
            deps = " ".join(engine.dependencies)
            result = subprocess.run(
                f"sudo apt-get install -y {deps}",
                shell=True, capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                log.warning(f"[EngineManager] Dependency install warning: {result.stderr}")
        
        # Clone repository
        if repo_dir.exists():
            update_progress(f"Updating {engine.display_name} source...")
            result = subprocess.run(
                ["git", "pull"],
                cwd=repo_dir, capture_output=True, text=True, timeout=120
            )
        else:
            update_progress(f"Cloning {engine.display_name} repository...")
            result = subprocess.run(
                ["git", "clone", "--depth", "1", engine.repo_url, str(repo_dir)],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                self._install_error = f"Clone failed: {result.stderr}"
                return False
        
        # Build
        update_progress(f"Building {engine.display_name}...")
        for cmd in engine.build_commands:
            result = subprocess.run(
                cmd,
                shell=True, cwd=repo_dir,
                capture_output=True, text=True, timeout=600
            )
            if result.returncode != 0:
                self._install_error = f"Build failed: {result.stderr}"
                return False
        
        # Copy binary to engines directory
        update_progress(f"Installing {engine.display_name}...")
        src_binary = repo_dir / engine.binary_path
        if not src_binary.exists():
            # Try to find the binary
            possible_paths = list(repo_dir.glob(f"**/{engine.name}"))
            if possible_paths:
                src_binary = possible_paths[0]
            else:
                self._install_error = f"Binary not found: {engine.binary_path}"
                return False
        
        dst_binary = self.engines_dir / engine.name
        shutil.copy2(src_binary, dst_binary)
        os.chmod(dst_binary, 0o755)
        
        # Copy extra files (personalities, books, weights, etc.)
        for extra in engine.extra_files:
            src_extra = repo_dir / extra
            if src_extra.exists():
                dst_extra = self.engines_dir / extra
                if src_extra.is_dir():
                    if dst_extra.exists():
                        shutil.rmtree(dst_extra)
                    shutil.copytree(src_extra, dst_extra)
                else:
                    shutil.copy2(src_extra, dst_extra)
        
        # Set ownership
        subprocess.run(
            ["sudo", "chown", "-R", "pi:pi", str(self.engines_dir)],
            capture_output=True, timeout=30
        )
        
        update_progress(f"{engine.display_name} installed successfully")
        return True
    
    def uninstall_engine(self, engine_name: str) -> bool:
        """Uninstall an engine.
        
        Args:
            engine_name: Name of the engine to uninstall
            
        Returns:
            True if uninstallation succeeded
        """
        if engine_name not in ENGINES:
            log.error(f"[EngineManager] Unknown engine: {engine_name}")
            return False
        
        engine = ENGINES[engine_name]
        
        if engine.is_system_package:
            # Don't uninstall system packages - just remove symlink
            link_path = self.engines_dir / engine.name
            if link_path.is_symlink():
                link_path.unlink()
                log.info(f"[EngineManager] Removed symlink: {link_path}")
            return True
        
        # Remove binary
        binary_path = self.engines_dir / engine.name
        if binary_path.exists():
            binary_path.unlink()
            log.info(f"[EngineManager] Removed: {binary_path}")
        
        # Remove extra files
        for extra in engine.extra_files:
            extra_path = self.engines_dir / extra
            if extra_path.exists():
                if extra_path.is_dir():
                    shutil.rmtree(extra_path)
                else:
                    extra_path.unlink()
                log.info(f"[EngineManager] Removed: {extra_path}")
        
        # Clean build directory
        build_dir = self.build_tmp / engine.name
        if build_dir.exists():
            shutil.rmtree(build_dir)
            log.info(f"[EngineManager] Cleaned build directory: {build_dir}")
        
        return True
    
    def install_async(
        self,
        engine_name: str,
        progress_callback: Optional[Callable[[str], None]] = None,
        completion_callback: Optional[Callable[[bool], None]] = None
    ) -> None:
        """Install an engine asynchronously.
        
        Args:
            engine_name: Name of the engine to install
            progress_callback: Called with progress messages
            completion_callback: Called with success status when done
        """
        def _install_thread():
            success = self.install_engine(engine_name, progress_callback)
            if completion_callback:
                completion_callback(success)
        
        self._install_thread = threading.Thread(
            target=_install_thread,
            name=f"install-{engine_name}",
            daemon=True
        )
        self._install_thread.start()
    
    def is_installing(self) -> bool:
        """Check if an installation is in progress."""
        return self._install_thread is not None and self._install_thread.is_alive()
    
    def get_install_progress(self) -> str:
        """Get the current installation progress message."""
        return self._install_progress
    
    def get_install_error(self) -> Optional[str]:
        """Get the last installation error, if any."""
        return self._install_error


# Module-level singleton
_engine_manager: Optional[EngineManager] = None


def get_engine_manager() -> EngineManager:
    """Get the engine manager singleton."""
    global _engine_manager
    if _engine_manager is None:
        _engine_manager = EngineManager()
    return _engine_manager
