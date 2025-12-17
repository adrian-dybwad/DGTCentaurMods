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
    summary: str                 # Short summary for list display (~20 chars)
    description: str             # Full description for detail view
    repo_url: Optional[str]      # Git repository URL (None for system package)
    build_commands: List[str]    # Commands to build after cloning
    binary_path: str             # Path to binary after build (relative to repo)
    is_system_package: bool      # True if installed via apt
    package_name: Optional[str]  # apt package name (if system package)
    extra_files: List[str]       # Additional files/dirs to copy (relative to repo)
    dependencies: List[str]      # apt packages needed to build
    can_uninstall: bool = True   # Whether engine can be uninstalled
    clone_with_submodules: bool = False  # Use --recurse-submodules when cloning
    build_timeout: int = 600     # Timeout for build commands in seconds (default 10 min)


# Engine definitions
# Ordered roughly by strength/popularity
ENGINES = {
    # === TOP TIER - World class engines ===
    "stockfish": EngineDefinition(
        name="stockfish",
        display_name="Stockfish",
        summary="~3500 ELO, #1 engine",
        description="World's strongest open-source chess engine. Uses NNUE neural network evaluation. The gold standard for computer chess analysis and play. Installed from system package - always available.",
        repo_url=None,
        build_commands=[],
        binary_path="",
        is_system_package=True,
        package_name="stockfish",
        extra_files=[],
        dependencies=[],
        can_uninstall=False,
    ),
    "berserk": EngineDefinition(
        name="berserk",
        display_name="Berserk",
        summary="~3400 ELO, top-3",
        description="Top-3 ranked open-source engine. Uses NNUE neural network for evaluation. Known for very strong tactical play and aggressive style. Excellent alternative to Stockfish.",
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
        summary="~3350 ELO, fast",
        description="Top-10 ranked engine with NNUE support. Known for fast search speed and aggressive playing style. Good for blitz and bullet games where speed matters.",
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
        summary="~3300 ELO, clean",
        description="Top-15 engine with NNUE. Known for clean, well-documented codebase. Great for those interested in chess programming. Solid positional play.",
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
        summary="~3200 ELO, fast",
        description="Strong C++ engine optimized for speed on modern CPUs. Excellent for rapid games. Good balance of tactical and positional play.",
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
        summary="~3100 ELO, tactical",
        description="Fast tactical engine known for quick search speed. Good for finding tactical shots and combinations. Lightweight and efficient.",
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
        summary="~2900 ELO, simple",
        description="Simple, efficient engine with clean C code. Fast to compile and run. Good for lower-powered devices. Solid but straightforward play.",
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
        summary="~2900 ELO, educational",
        description="Clean, educational engine great for learning chess programming. Well-commented source code. Solid playing strength despite simplicity.",
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
        summary="~2900 ELO, veteran",
        description="Veteran engine in development since 1994. Very stable and reliable. NNUE support added recently. Great for consistent, predictable play.",
        repo_url="https://github.com/jdart1/arasan-chess.git",
        build_commands=[
            "cd src && make -j$(nproc)",
        ],
        binary_path="src/arasan",
        is_system_package=False,
        package_name=None,
        extra_files=[],
        dependencies=["build-essential", "git", "bc"],
    ),
    
    # === SPECIALTY ENGINES ===
    "rodentIV": EngineDefinition(
        name="rodentIV",
        display_name="Rodent IV",
        summary="~2800 ELO, 50+ styles",
        description="Personality engine with 50+ playing styles from beginner to GM level. Can emulate famous players or specific playing styles. Great for practice and entertainment.",
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
        summary="~2300 ELO, retro",
        description="Emulates a dedicated chess computer. Classic playing style reminiscent of 1980s chess computers. Good for casual play with a nostalgic feel.",
        repo_url="https://github.com/bcm314/CT800.git",
        build_commands=[
            # Build produces ct800 binary in the uci directory
            "cd src/application/uci && make -j$(nproc)",
        ],
        # Binary name is ct800 (lowercase) after build
        binary_path="src/application/uci/ct800",
        is_system_package=False,
        package_name=None,
        extra_files=[],
        dependencies=["build-essential", "git"],
    ),
    
    # === NEURAL NETWORK - HUMAN-LIKE ===
    "maia": EngineDefinition(
        name="maia",
        display_name="Maia",
        summary="Human-like play",
        description="Trained on millions of human games to play like humans at various ELO levels (1100-1900). Uses lc0 backend with Maia neural network weights. Makes realistic human moves and mistakes.",
        repo_url="https://github.com/LeelaChessZero/lc0.git",
        build_commands=[
            # Build lc0 with BLAS backend (CPU-only, no GPU needed)
            "./build.sh",
            # Download all Maia weights (1100-1900 ELO levels)
            "mkdir -p maia_weights",
            "wget -q -O maia_weights/maia-1100.pb.gz https://github.com/CSSLab/maia-chess/raw/main/maia_weights/maia-1100.pb.gz || true",
            "wget -q -O maia_weights/maia-1200.pb.gz https://github.com/CSSLab/maia-chess/raw/main/maia_weights/maia-1200.pb.gz || true",
            "wget -q -O maia_weights/maia-1300.pb.gz https://github.com/CSSLab/maia-chess/raw/main/maia_weights/maia-1300.pb.gz || true",
            "wget -q -O maia_weights/maia-1400.pb.gz https://github.com/CSSLab/maia-chess/raw/main/maia_weights/maia-1400.pb.gz || true",
            "wget -q -O maia_weights/maia-1500.pb.gz https://github.com/CSSLab/maia-chess/raw/main/maia_weights/maia-1500.pb.gz || true",
            "wget -q -O maia_weights/maia-1600.pb.gz https://github.com/CSSLab/maia-chess/raw/main/maia_weights/maia-1600.pb.gz || true",
            "wget -q -O maia_weights/maia-1700.pb.gz https://github.com/CSSLab/maia-chess/raw/main/maia_weights/maia-1700.pb.gz || true",
            "wget -q -O maia_weights/maia-1800.pb.gz https://github.com/CSSLab/maia-chess/raw/main/maia_weights/maia-1800.pb.gz || true",
            "wget -q -O maia_weights/maia-1900.pb.gz https://github.com/CSSLab/maia-chess/raw/main/maia_weights/maia-1900.pb.gz || true",
        ],
        binary_path="build/release/lc0",
        is_system_package=False,
        package_name=None,
        extra_files=["maia_weights"],
        dependencies=["build-essential", "git", "meson", "ninja-build", "libopenblas-dev", "python3-pip", "wget"],
        clone_with_submodules=True,
        build_timeout=1800,  # 30 min - lc0 takes a long time to build
    ),
    
    # === LIGHTWEIGHT/FAST COMPILE ===
    "zahak": EngineDefinition(
        name="zahak",
        display_name="Zahak",
        summary="~2700 ELO, Go-based",
        description="Written in Go programming language. Clean, modern codebase under active development. Good strength with fast compilation. Interesting alternative architecture.",
        repo_url="https://github.com/amanjpro/zahak.git",
        build_commands=[
            "go build -o zahak",
        ],
        binary_path="zahak",
        is_system_package=False,
        package_name=None,
        extra_files=[],
        # golang package name varies: 'golang' on older Debian, 'golang-go' on newer
        dependencies=["golang", "git"],
    ),
    "smallbrain": EngineDefinition(
        name="smallbrain",
        display_name="Smallbrain",
        summary="~3000 ELO, compact",
        description="Compact NNUE engine with small binary size. Efficient code optimized for resource-constrained devices. Surprisingly strong for its size.",
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
        self._installing_engine: Optional[str] = None
        
        log.info(f"[EngineManager] Initialized with engines_dir={engines_dir}")
        log.debug(f"[EngineManager] Build temp directory: {BUILD_TMP}")
        log.debug(f"[EngineManager] Available engines: {list(ENGINES.keys())}")
    
    def is_installed(self, engine_name: str) -> bool:
        """Check if an engine is installed.
        
        Args:
            engine_name: Name of the engine to check
            
        Returns:
            True if the engine executable exists
        """
        if engine_name not in ENGINES:
            log.warning(f"[EngineManager] is_installed: Unknown engine '{engine_name}'")
            return False
        
        engine = ENGINES[engine_name]
        
        if engine.is_system_package:
            # Check if system command exists
            system_path = shutil.which(engine_name)
            is_installed = system_path is not None
            log.debug(f"[EngineManager] is_installed: {engine_name} (system package) = {is_installed}, path={system_path}")
            return is_installed
        else:
            # Check if binary exists in engines directory
            engine_path = self.engines_dir / engine_name
            exists = engine_path.exists()
            executable = os.access(engine_path, os.X_OK) if exists else False
            is_installed = exists and executable
            log.debug(f"[EngineManager] is_installed: {engine_name} = {is_installed} (exists={exists}, executable={executable}, path={engine_path})")
            return is_installed
    
    def get_engine_list(self) -> List[dict]:
        """Get list of all engines with installation status.
        
        Returns:
            List of dicts with engine info and installed status
        """
        log.debug("[EngineManager] get_engine_list: Building engine list")
        result = []
        installed_count = 0
        for name, engine in ENGINES.items():
            is_installed = self.is_installed(name)
            if is_installed:
                installed_count += 1
            result.append({
                "name": name,
                "display_name": engine.display_name,
                "summary": engine.summary,
                "description": engine.description,
                "installed": is_installed,
                "is_system_package": engine.is_system_package,
                "can_uninstall": engine.can_uninstall,
            })
        log.info(f"[EngineManager] get_engine_list: {installed_count}/{len(ENGINES)} engines installed")
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
        log.info(f"[EngineManager] install_engine: Starting installation of '{engine_name}'")
        
        if engine_name not in ENGINES:
            log.error(f"[EngineManager] install_engine: Unknown engine '{engine_name}' - not in ENGINES dict")
            self._install_error = f"Unknown engine: {engine_name}"
            return False
        
        engine = ENGINES[engine_name]
        self._installing_engine = engine_name
        self._install_error = None
        
        log.info(f"[EngineManager] install_engine: Engine details - display_name='{engine.display_name}', "
                 f"is_system_package={engine.is_system_package}, repo_url={engine.repo_url}")
        
        def update_progress(msg: str):
            self._install_progress = msg
            log.info(f"[EngineManager] [Progress] {msg}")
            if progress_callback:
                progress_callback(msg)
        
        try:
            if engine.is_system_package:
                log.info(f"[EngineManager] install_engine: Using system package installation for '{engine_name}'")
                success = self._install_system_package(engine, update_progress)
            else:
                log.info(f"[EngineManager] install_engine: Using source build installation for '{engine_name}'")
                success = self._install_from_source(engine, update_progress)
            
            if success:
                log.info(f"[EngineManager] install_engine: Successfully installed '{engine_name}'")
            else:
                log.error(f"[EngineManager] install_engine: Failed to install '{engine_name}' - error: {self._install_error}")
            
            return success
        except subprocess.TimeoutExpired as e:
            self._install_error = f"Command timed out: {e.cmd}"
            log.error(f"[EngineManager] install_engine: Timeout during installation of '{engine_name}': {e}")
            return False
        except subprocess.SubprocessError as e:
            self._install_error = f"Subprocess error: {e}"
            log.error(f"[EngineManager] install_engine: Subprocess error during installation of '{engine_name}': {e}")
            return False
        except OSError as e:
            self._install_error = f"OS error: {e}"
            log.error(f"[EngineManager] install_engine: OS error during installation of '{engine_name}': {e}")
            return False
        except Exception as e:
            self._install_error = str(e)
            log.error(f"[EngineManager] install_engine: Unexpected exception during installation of '{engine_name}': {type(e).__name__}: {e}")
            import traceback
            log.error(f"[EngineManager] install_engine: Traceback:\n{traceback.format_exc()}")
            return False
        finally:
            self._installing_engine = None
    
    def _install_system_package(
        self,
        engine: EngineDefinition,
        update_progress: Callable[[str], None]
    ) -> bool:
        """Install engine from system package.
        
        Args:
            engine: Engine definition
            update_progress: Callback for progress messages
            
        Returns:
            True if installation succeeded
        """
        log.info(f"[EngineManager] _install_system_package: Installing '{engine.name}' via apt package '{engine.package_name}'")
        update_progress(f"Installing {engine.display_name} from system package...")
        
        # Update package list
        log.debug("[EngineManager] _install_system_package: Running apt-get update")
        result = subprocess.run(
            ["sudo", "apt-get", "update", "-qq"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            log.warning(f"[EngineManager] _install_system_package: apt-get update returned non-zero ({result.returncode})")
            log.warning(f"[EngineManager] _install_system_package: apt-get update stderr: {result.stderr.strip()}")
        else:
            log.debug("[EngineManager] _install_system_package: apt-get update completed successfully")
        
        # Install package
        update_progress(f"Installing {engine.package_name}...")
        log.info(f"[EngineManager] _install_system_package: Running apt-get install -y {engine.package_name}")
        result = subprocess.run(
            ["sudo", "apt-get", "install", "-y", engine.package_name],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            self._install_error = result.stderr.strip() or f"apt-get install failed with code {result.returncode}"
            log.error(f"[EngineManager] _install_system_package: apt-get install failed with code {result.returncode}")
            log.error(f"[EngineManager] _install_system_package: stdout: {result.stdout.strip()}")
            log.error(f"[EngineManager] _install_system_package: stderr: {result.stderr.strip()}")
            return False
        
        log.info(f"[EngineManager] _install_system_package: apt-get install completed successfully")
        if result.stdout.strip():
            log.debug(f"[EngineManager] _install_system_package: stdout: {result.stdout.strip()[:200]}")
        
        # Create symlink in engines directory
        system_path = shutil.which(engine.name)
        if system_path:
            log.info(f"[EngineManager] _install_system_package: Found system binary at {system_path}")
            link_path = self.engines_dir / engine.name
            
            # Ensure engines directory exists
            if not self.engines_dir.exists():
                log.info(f"[EngineManager] _install_system_package: Creating engines directory {self.engines_dir}")
                self.engines_dir.mkdir(parents=True, exist_ok=True)
            
            if link_path.exists() or link_path.is_symlink():
                log.debug(f"[EngineManager] _install_system_package: Removing existing file/symlink at {link_path}")
                link_path.unlink(missing_ok=True)
            
            link_path.symlink_to(system_path)
            log.info(f"[EngineManager] _install_system_package: Created symlink {link_path} -> {system_path}")
            update_progress(f"Created symlink: {link_path} -> {system_path}")
        else:
            log.warning(f"[EngineManager] _install_system_package: Could not find '{engine.name}' in PATH after installation")
        
        update_progress(f"{engine.display_name} installed successfully")
        log.info(f"[EngineManager] _install_system_package: Successfully installed '{engine.name}'")
        return True
    
    def _install_from_source(
        self,
        engine: EngineDefinition,
        update_progress: Callable[[str], None]
    ) -> bool:
        """Install engine by building from source.
        
        Args:
            engine: Engine definition
            update_progress: Callback for progress messages
            
        Returns:
            True if installation succeeded
        """
        log.info(f"[EngineManager] _install_from_source: Starting source build for '{engine.name}'")
        log.info(f"[EngineManager] _install_from_source: Repo URL: {engine.repo_url}")
        log.info(f"[EngineManager] _install_from_source: Build commands: {engine.build_commands}")
        log.info(f"[EngineManager] _install_from_source: Binary path: {engine.binary_path}")
        
        # Ensure build directory exists
        log.debug(f"[EngineManager] _install_from_source: Creating build temp directory {self.build_tmp}")
        self.build_tmp.mkdir(parents=True, exist_ok=True)
        repo_dir = self.build_tmp / engine.name
        log.debug(f"[EngineManager] _install_from_source: Repo directory: {repo_dir}")
        
        # Install build dependencies
        if engine.dependencies:
            update_progress(f"Installing build dependencies...")
            deps = " ".join(engine.dependencies)
            log.info(f"[EngineManager] _install_from_source: Installing dependencies: {deps}")
            result = subprocess.run(
                f"sudo apt-get install -y {deps}",
                shell=True, capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                log.warning(f"[EngineManager] _install_from_source: Dependency install returned non-zero ({result.returncode})")
                log.warning(f"[EngineManager] _install_from_source: Dependency stderr: {result.stderr.strip()}")
            else:
                log.info(f"[EngineManager] _install_from_source: Dependencies installed successfully")
        else:
            log.debug(f"[EngineManager] _install_from_source: No dependencies to install")
        
        # Clone or update repository
        if repo_dir.exists():
            update_progress(f"Updating {engine.display_name} source...")
            log.info(f"[EngineManager] _install_from_source: Repo exists, running git pull in {repo_dir}")
            result = subprocess.run(
                ["git", "pull"],
                cwd=repo_dir, capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                log.warning(f"[EngineManager] _install_from_source: git pull failed ({result.returncode}): {result.stderr.strip()}")
                # Try to continue anyway - maybe just network issue
            else:
                log.info(f"[EngineManager] _install_from_source: git pull successful")
            
            # Update submodules if needed
            if engine.clone_with_submodules:
                update_progress(f"Updating submodules...")
                log.info(f"[EngineManager] _install_from_source: Updating submodules")
                result = subprocess.run(
                    ["git", "submodule", "update", "--init", "--recursive"],
                    cwd=repo_dir, capture_output=True, text=True, timeout=300
                )
                if result.returncode != 0:
                    log.warning(f"[EngineManager] _install_from_source: submodule update failed: {result.stderr.strip()}")
        else:
            update_progress(f"Cloning {engine.display_name} repository...")
            log.info(f"[EngineManager] _install_from_source: Cloning {engine.repo_url} to {repo_dir}")
            
            # Build clone command - use submodules if needed
            clone_cmd = ["git", "clone"]
            if engine.clone_with_submodules:
                clone_cmd.extend(["--recurse-submodules"])
            else:
                clone_cmd.extend(["--depth", "1"])
            clone_cmd.extend([engine.repo_url, str(repo_dir)])
            
            log.info(f"[EngineManager] _install_from_source: Clone command: {' '.join(clone_cmd)}")
            result = subprocess.run(
                clone_cmd,
                capture_output=True, text=True, timeout=600  # Longer timeout for submodules
            )
            if result.returncode != 0:
                self._install_error = f"Clone failed: {result.stderr.strip()}"
                log.error(f"[EngineManager] _install_from_source: git clone failed ({result.returncode})")
                log.error(f"[EngineManager] _install_from_source: git clone stdout: {result.stdout.strip()}")
                log.error(f"[EngineManager] _install_from_source: git clone stderr: {result.stderr.strip()}")
                return False
            log.info(f"[EngineManager] _install_from_source: git clone successful")
        
        # Build
        update_progress(f"Building {engine.display_name}...")
        for i, cmd in enumerate(engine.build_commands):
            log.info(f"[EngineManager] _install_from_source: Running build command {i+1}/{len(engine.build_commands)}: {cmd}")
            log.info(f"[EngineManager] _install_from_source: Build timeout: {engine.build_timeout}s")
            result = subprocess.run(
                cmd,
                shell=True, cwd=repo_dir,
                capture_output=True, text=True, timeout=engine.build_timeout
            )
            if result.returncode != 0:
                self._install_error = f"Build failed: {result.stderr.strip()[:100]}"
                log.error(f"[EngineManager] _install_from_source: Build command failed ({result.returncode}): {cmd}")
                log.error(f"[EngineManager] _install_from_source: Build stdout (last 500 chars): {result.stdout.strip()[-500:]}")
                log.error(f"[EngineManager] _install_from_source: Build stderr (last 500 chars): {result.stderr.strip()[-500:]}")
                return False
            log.debug(f"[EngineManager] _install_from_source: Build command {i+1} completed successfully")
        
        log.info(f"[EngineManager] _install_from_source: All build commands completed successfully")
        
        # Ensure engines directory exists
        if not self.engines_dir.exists():
            log.info(f"[EngineManager] _install_from_source: Creating engines directory {self.engines_dir}")
            self.engines_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy binary to engines directory
        update_progress(f"Installing {engine.display_name}...")
        src_binary = repo_dir / engine.binary_path
        log.debug(f"[EngineManager] _install_from_source: Looking for binary at {src_binary}")
        
        if not src_binary.exists():
            # Try to find the binary
            log.warning(f"[EngineManager] _install_from_source: Binary not found at expected path {src_binary}")
            log.info(f"[EngineManager] _install_from_source: Searching for binary named '{engine.name}' in repo")
            possible_paths = list(repo_dir.glob(f"**/{engine.name}"))
            log.debug(f"[EngineManager] _install_from_source: Found {len(possible_paths)} potential matches: {possible_paths}")
            
            if possible_paths:
                src_binary = possible_paths[0]
                log.info(f"[EngineManager] _install_from_source: Using found binary at {src_binary}")
            else:
                # List directory contents for debugging
                log.error(f"[EngineManager] _install_from_source: Binary not found anywhere in repo")
                try:
                    all_files = list(repo_dir.rglob("*"))
                    executables = [f for f in all_files if f.is_file() and os.access(f, os.X_OK)]
                    log.error(f"[EngineManager] _install_from_source: Executable files in repo: {executables[:20]}")
                except Exception as e:
                    log.error(f"[EngineManager] _install_from_source: Could not list repo files: {e}")
                
                self._install_error = f"Binary not found: {engine.binary_path}"
                return False
        
        dst_binary = self.engines_dir / engine.name
        log.info(f"[EngineManager] _install_from_source: Copying binary {src_binary} -> {dst_binary}")
        shutil.copy2(src_binary, dst_binary)
        os.chmod(dst_binary, 0o755)
        log.info(f"[EngineManager] _install_from_source: Binary installed and made executable")
        
        # Copy extra files (personalities, books, weights, etc.)
        if engine.extra_files:
            log.info(f"[EngineManager] _install_from_source: Copying {len(engine.extra_files)} extra files/directories")
        for extra in engine.extra_files:
            src_extra = repo_dir / extra
            if src_extra.exists():
                dst_extra = self.engines_dir / extra
                log.debug(f"[EngineManager] _install_from_source: Copying extra '{extra}': {src_extra} -> {dst_extra}")
                if src_extra.is_dir():
                    if dst_extra.exists():
                        log.debug(f"[EngineManager] _install_from_source: Removing existing directory {dst_extra}")
                        shutil.rmtree(dst_extra)
                    shutil.copytree(src_extra, dst_extra)
                    log.debug(f"[EngineManager] _install_from_source: Copied directory {extra}")
                else:
                    shutil.copy2(src_extra, dst_extra)
                    log.debug(f"[EngineManager] _install_from_source: Copied file {extra}")
            else:
                log.warning(f"[EngineManager] _install_from_source: Extra file/dir not found: {src_extra}")
        
        # Set ownership
        log.debug(f"[EngineManager] _install_from_source: Setting ownership to pi:pi on {self.engines_dir}")
        result = subprocess.run(
            ["sudo", "chown", "-R", "pi:pi", str(self.engines_dir)],
            capture_output=True, timeout=30
        )
        if result.returncode != 0:
            log.warning(f"[EngineManager] _install_from_source: chown failed ({result.returncode})")
        
        update_progress(f"{engine.display_name} installed successfully")
        log.info(f"[EngineManager] _install_from_source: Successfully installed '{engine.name}'")
        return True
    
    def uninstall_engine(self, engine_name: str) -> bool:
        """Uninstall an engine.
        
        Args:
            engine_name: Name of the engine to uninstall
            
        Returns:
            True if uninstallation succeeded
        """
        log.info(f"[EngineManager] uninstall_engine: Starting uninstallation of '{engine_name}'")
        
        if engine_name not in ENGINES:
            log.error(f"[EngineManager] uninstall_engine: Unknown engine '{engine_name}' - not in ENGINES dict")
            return False
        
        engine = ENGINES[engine_name]
        
        if not engine.can_uninstall:
            log.warning(f"[EngineManager] uninstall_engine: Engine '{engine_name}' cannot be uninstalled (can_uninstall=False)")
            return False
        
        if engine.is_system_package:
            # Don't uninstall system packages - just remove symlink
            log.info(f"[EngineManager] uninstall_engine: '{engine_name}' is system package, only removing symlink")
            link_path = self.engines_dir / engine.name
            if link_path.is_symlink():
                link_path.unlink()
                log.info(f"[EngineManager] uninstall_engine: Removed symlink {link_path}")
            elif link_path.exists():
                log.warning(f"[EngineManager] uninstall_engine: {link_path} exists but is not a symlink")
            else:
                log.debug(f"[EngineManager] uninstall_engine: No symlink found at {link_path}")
            return True
        
        # Remove binary
        binary_path = self.engines_dir / engine.name
        if binary_path.exists():
            try:
                binary_path.unlink()
                log.info(f"[EngineManager] uninstall_engine: Removed binary {binary_path}")
            except OSError as e:
                log.error(f"[EngineManager] uninstall_engine: Failed to remove binary {binary_path}: {e}")
        else:
            log.debug(f"[EngineManager] uninstall_engine: Binary not found at {binary_path}")
        
        # Remove extra files
        for extra in engine.extra_files:
            extra_path = self.engines_dir / extra
            if extra_path.exists():
                try:
                    if extra_path.is_dir():
                        shutil.rmtree(extra_path)
                        log.info(f"[EngineManager] uninstall_engine: Removed directory {extra_path}")
                    else:
                        extra_path.unlink()
                        log.info(f"[EngineManager] uninstall_engine: Removed file {extra_path}")
                except OSError as e:
                    log.error(f"[EngineManager] uninstall_engine: Failed to remove {extra_path}: {e}")
            else:
                log.debug(f"[EngineManager] uninstall_engine: Extra file/dir not found: {extra_path}")
        
        # Clean build directory
        build_dir = self.build_tmp / engine.name
        if build_dir.exists():
            try:
                shutil.rmtree(build_dir)
                log.info(f"[EngineManager] uninstall_engine: Cleaned build directory {build_dir}")
            except OSError as e:
                log.warning(f"[EngineManager] uninstall_engine: Failed to clean build directory {build_dir}: {e}")
        else:
            log.debug(f"[EngineManager] uninstall_engine: No build directory at {build_dir}")
        
        log.info(f"[EngineManager] uninstall_engine: Successfully uninstalled '{engine_name}'")
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
        log.info(f"[EngineManager] install_async: Starting async installation of '{engine_name}'")
        
        if self.is_installing():
            log.warning(f"[EngineManager] install_async: Another installation is already in progress "
                       f"(installing: {self._installing_engine})")
            if completion_callback:
                completion_callback(False)
            return
        
        def _install_thread():
            log.debug(f"[EngineManager] install_async: Install thread started for '{engine_name}'")
            try:
                success = self.install_engine(engine_name, progress_callback)
                log.info(f"[EngineManager] install_async: Install thread completed for '{engine_name}', success={success}")
                if completion_callback:
                    completion_callback(success)
            except Exception as e:
                log.error(f"[EngineManager] install_async: Install thread crashed for '{engine_name}': {type(e).__name__}: {e}")
                import traceback
                log.error(f"[EngineManager] install_async: Traceback:\n{traceback.format_exc()}")
                self._install_error = str(e)
                if completion_callback:
                    completion_callback(False)
        
        self._install_thread = threading.Thread(
            target=_install_thread,
            name=f"install-{engine_name}",
            daemon=True
        )
        self._install_thread.start()
        log.debug(f"[EngineManager] install_async: Install thread spawned for '{engine_name}'")
    
    def is_installing(self) -> bool:
        """Check if an installation is in progress."""
        is_running = self._install_thread is not None and self._install_thread.is_alive()
        return is_running
    
    def get_installing_engine(self) -> Optional[str]:
        """Get the name of the engine currently being installed, if any."""
        if self.is_installing():
            return self._installing_engine
        return None
    
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
