#!/usr/bin/env bash
# Build script for lc0 (Leela Chess Zero) on Raspberry Pi ARM
#
# This script builds lc0 with BLAS backend for CPU-only operation.
# It handles both 32-bit and 64-bit ARM architectures.
#
# Usage: ./build-lc0.sh [output_dir]
#   output_dir: Where to place the built binary (default: current directory)
#
# Prerequisites installed by this script if missing:
#   - build-essential, git, clang, meson, ninja-build
#   - libopenblas-dev (or builds OpenBLAS from source if needed)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${1:-$(pwd)}"
BUILD_DIR="/tmp/lc0-build-$$"
LC0_VERSION="v0.32.1"  # Update as needed

# Maia weights to download
MAIA_WEIGHTS=(
    "maia-1100.pb.gz"
    "maia-1200.pb.gz"
    "maia-1300.pb.gz"
    "maia-1400.pb.gz"
    "maia-1500.pb.gz"
    "maia-1600.pb.gz"
    "maia-1700.pb.gz"
    "maia-1800.pb.gz"
    "maia-1900.pb.gz"
)
MAIA_WEIGHTS_URL="https://github.com/CSSLab/maia-chess/raw/main/maia_weights"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
}

cleanup() {
    if [[ -d "$BUILD_DIR" ]]; then
        log "Cleaning up build directory..."
        rm -rf "$BUILD_DIR"
    fi
}

trap cleanup EXIT

detect_arch() {
    local arch
    arch=$(uname -m)
    case "$arch" in
        aarch64|arm64)
            echo "arm64"
            ;;
        armv7l|armhf)
            echo "arm32"
            ;;
        x86_64)
            echo "x86_64"
            ;;
        *)
            error "Unsupported architecture: $arch"
            exit 1
            ;;
    esac
}

install_dependencies() {
    log "Installing build dependencies..."
    
    # Check if we can use apt
    if ! command -v apt-get &>/dev/null; then
        error "apt-get not found. This script is designed for Debian-based systems."
        exit 1
    fi
    
    # Core build tools
    sudo apt-get update
    sudo apt-get install -y \
        build-essential \
        git \
        clang \
        meson \
        ninja-build \
        pkg-config \
        libopenblas-dev \
        zlib1g-dev \
        wget
    
    # Ensure meson is up to date (apt version may be too old)
    if ! python3 -m pip show meson &>/dev/null; then
        log "Installing latest meson via pip..."
        python3 -m pip install --user meson
    fi
}

build_lc0() {
    local arch="$1"
    
    log "Building lc0 for $arch..."
    
    mkdir -p "$BUILD_DIR"
    cd "$BUILD_DIR"
    
    # Clone lc0
    log "Cloning lc0 repository (tag: $LC0_VERSION)..."
    git clone --depth 1 --branch "$LC0_VERSION" --recurse-submodules \
        https://github.com/LeelaChessZero/lc0.git
    
    cd lc0
    
    # Apply ARM-specific patches if needed
    apply_arm_patches "$arch"
    
    # Configure build options based on architecture
    # Using correct lc0 meson option names (see meson_options.txt)
    local build_opts="-Ddefault_library=static"
    
    # Enable BLAS backend (CPU only, works on all ARM)
    build_opts="$build_opts -Dblas=true -Dopenblas=true"
    
    # Disable GPU backends (not available on Pi)
    # Note: lc0 uses "plain_cuda" not "cuda"
    build_opts="$build_opts -Dplain_cuda=false -Dcudnn=false -Dopencl=false -Ddx=false -Donednn=false -Dmetal=disabled"
    
    # Disable x86-specific features that don't exist on ARM
    build_opts="$build_opts -Dispc=false -Dpopcnt=false -Df16c=false -Dpext=false"
    
    # Disable optional features we don't need
    build_opts="$build_opts -Dgtest=false -Donnx=false -Dnvcc=false -Dpython_bindings=false"
    
    log "Configuring build with options: $build_opts"
    
    # Use clang for better ARM optimization
    export CC=clang
    export CXX=clang++
    
    # Don't use build.sh - it runs ninja with full parallelism which can OOM on Pi
    # Instead, manually run meson and ninja with limited parallelism
    log "Running meson setup..."
    meson setup build/release --buildtype=release $build_opts
    
    # Build with -j2 to avoid OOM kills on Raspberry Pi
    # Full parallelism (-j4 or more) can exhaust RAM during C++ compilation
    log "Running ninja with -j2 (limited parallelism to avoid OOM)..."
    if ! ninja -C build/release -j2; then
        error "Build failed with -j2. Trying -j1..."
        # Last resort: single-threaded build
        ninja -C build/release -j1
    fi
    
    # Check if binary was created
    if [[ ! -f "build/release/lc0" ]]; then
        error "lc0 binary not found after build"
        exit 1
    fi
    
    log "Build successful!"
}

apply_arm_patches() {
    local arch="$1"
    
    log "Applying ARM-specific patches..."
    
    # Patch abseil to remove problematic NEON assumptions on 32-bit ARM
    # This addresses the -mfpu=neon issue mentioned in Yocto patches
    if [[ "$arch" == "arm32" ]]; then
        # Find and patch abseil's copts if it assumes NEON
        if [[ -f "subprojects/abseil-cpp-*/absl/copts/copts.py" ]]; then
            log "Patching abseil copts for 32-bit ARM..."
            find subprojects -name "copts.py" -path "*abseil*" -exec \
                sed -i 's/-mfpu=neon//g' {} \;
        fi
    fi
    
    # For arm64, we generally don't need patches as NEON is always available
}

download_maia_weights() {
    local output_dir="$1"
    local weights_dir="$output_dir/maia_weights"
    
    log "Downloading Maia neural network weights..."
    
    mkdir -p "$weights_dir"
    
    for weight in "${MAIA_WEIGHTS[@]}"; do
        local url="$MAIA_WEIGHTS_URL/$weight"
        local dest="$weights_dir/$weight"
        
        if [[ -f "$dest" ]]; then
            log "  $weight already exists, skipping"
        else
            log "  Downloading $weight..."
            if ! wget -q -O "$dest" "$url"; then
                error "Failed to download $weight"
                # Continue anyway, some weights may be optional
            fi
        fi
    done
    
    log "Maia weights downloaded to $weights_dir"
}

install_binary() {
    local output_dir="$1"
    
    log "Installing lc0 binary to $output_dir..."
    
    mkdir -p "$output_dir"
    
    # Copy the binary
    cp "$BUILD_DIR/lc0/build/release/lc0" "$output_dir/lc0"
    chmod +x "$output_dir/lc0"
    
    # Strip the binary to reduce size
    strip "$output_dir/lc0" 2>/dev/null || true
    
    log "lc0 installed to $output_dir/lc0"
    
    # Show binary info
    file "$output_dir/lc0"
    ls -lh "$output_dir/lc0"
}

main() {
    log "=== lc0 Build Script for Raspberry Pi ==="
    
    local arch
    arch=$(detect_arch)
    log "Detected architecture: $arch"
    
    # Check if running on ARM
    if [[ "$arch" != "arm64" && "$arch" != "arm32" ]]; then
        error "This script is intended for ARM (Raspberry Pi). Detected: $arch"
        error "For other architectures, download official binaries from:"
        error "  https://github.com/LeelaChessZero/lc0/releases"
        exit 1
    fi
    
    install_dependencies
    build_lc0 "$arch"
    install_binary "$OUTPUT_DIR"
    download_maia_weights "$OUTPUT_DIR"
    
    log "=== Build Complete ==="
    log "Binary: $OUTPUT_DIR/lc0"
    log "Weights: $OUTPUT_DIR/maia_weights/"
    log ""
    log "To use Maia, run:"
    log "  $OUTPUT_DIR/lc0 --weights=$OUTPUT_DIR/maia_weights/maia-1500.pb.gz"
}

main "$@"

