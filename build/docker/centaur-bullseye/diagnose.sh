#!/bin/bash
# Diagnostic script to check what's missing for the centaur binary in Docker

# Don't exit on error - we want to see all diagnostics
set +e

echo "=== Centaur Binary Diagnostic ==="
echo ""

# Check if binary exists
if [ ! -f /centaur/centaur ]; then
    echo "ERROR: /centaur/centaur not found"
    exit 1
fi

echo "1. Binary information:"
ls -lh /centaur/centaur
file /centaur/centaur
echo ""

echo "2. Checking library dependencies:"
if command -v ldd &> /dev/null; then
    ldd /centaur/centaur || true
else
    echo "ldd not available, installing..."
    apt-get update -qq && apt-get install -y -qq binutils > /dev/null 2>&1
    ldd /centaur/centaur || true
fi
echo ""

echo "3. Checking for missing libraries:"
MISSING_LIBS=0
for lib in $(ldd /centaur/centaur 2>/dev/null | grep "not found" | awk '{print $1}'); do
    echo "  MISSING: $lib"
    MISSING_LIBS=1
done
if [ $MISSING_LIBS -eq 0 ]; then
    echo "  All libraries found"
fi
echo ""

echo "4. Checking required directories:"
for dir in settings engines fonts books RPi PIL; do
    if [ -d "/centaur/$dir" ]; then
        echo "  ✓ $dir exists"
    else
        echo "  ✗ $dir MISSING"
    fi
done
echo ""

echo "5. Checking required .so files in /centaur:"
REQUIRED_SO=(
    "libpython3.5m.so.1.0"
    "libexpat.so.1"
    "libz.so.1"
    "libgcc_s.so.1"
    "libutil.so.1"
)
for so in "${REQUIRED_SO[@]}"; do
    if [ -f "/centaur/$so" ]; then
        echo "  ✓ $so exists"
    else
        echo "  ✗ $so MISSING"
    fi
done
echo ""

echo "6. Testing binary execution with strace (last 20 system calls):"
if command -v strace &> /dev/null; then
    echo "Running with strace..."
    timeout 2 strace -e trace=all /centaur/centaur 2>&1 | tail -20 || true
else
    echo "strace not available, installing..."
    apt-get update -qq && apt-get install -y -qq strace > /dev/null 2>&1
    timeout 2 strace -e trace=all /centaur/centaur 2>&1 | tail -20 || true
fi
echo ""

echo "=== Diagnostic Complete ==="
