#!/bin/bash
# Test runner script for promotion button handling tests
# Run this from the opt folder

echo "Starting Promotion Button Handling Tests"
echo "========================================"

# Check if we're in the right directory
if [ ! -d "DGTCentaurMods" ]; then
    echo "ERROR: Please run this script from the opt folder"
    echo "Current directory: $(pwd)"
    echo "Expected to find: DGTCentaurMods directory"
    exit 1
fi

# Activate virtual environment
echo "Activating virtual environment..."
source DGTCentaurMods/.venv/bin/activate

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to activate virtual environment"
    echo "Make sure DGTCentaurMods/.venv exists"
    exit 1
fi

echo "Virtual environment activated"
echo ""

# Parse command line arguments
TEST_TYPE="simple"
POSITION="both"
HARDWARE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --hardware)
            HARDWARE=true
            shift
            ;;
        --position)
            POSITION="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [--hardware] [--position white|black|both]"
            echo ""
            echo "Options:"
            echo "  --hardware    Run hardware-in-the-loop tests"
            echo "  --position    Test specific promotion position (default: both)"
            echo "  --help        Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                                    # Run simple tests only"
            echo "  $0 --hardware                        # Run hardware tests"
            echo "  $0 --hardware --position white       # Test white promotion only"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Run the appropriate test
if [ "$HARDWARE" = true ]; then
    echo "Running hardware-in-the-loop tests..."
    echo "Position: $POSITION"
    echo ""
    python3 DGTCentaurMods/tests/test_promotion_simple_hardware.py --hardware --position "$POSITION"
else
    echo "Running simple tests..."
    echo ""
    python3 DGTCentaurMods/tests/test_promotion_simple.py
fi

echo ""
echo "Test run complete!"
