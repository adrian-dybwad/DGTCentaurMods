#!/bin/bash
# scripts/run-react.sh
#
# Starts the React web app development server.
# Proxies API calls to a backend server.
#
# Usage:
#   ./scripts/run-react.sh [--api URL]
#
# Options:
#   --api URL    Backend API URL to proxy to (default: http://dgt.local)
#
# Examples:
#   ./scripts/run-react.sh                        # Uses http://dgt.local
#   ./scripts/run-react.sh --api http://dgt.local
#   ./scripts/run-react.sh --api http://localhost:5000
#
# Prerequisites:
#   - Node.js and npm installed
#   - Backend server running at the specified URL
#

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
WEB_APP_DIR="${REPO_ROOT}/src/universalchess/web-app"

# Default API URL
API_URL="http://dgt.local"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --api)
            API_URL="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $(basename "$0") [--api URL]"
            echo ""
            echo "Options:"
            echo "  --api URL    Backend API URL to proxy to (default: http://dgt.local)"
            echo ""
            echo "Examples:"
            echo "  $(basename "$0")                        # Uses http://dgt.local"
            echo "  $(basename "$0") --api http://localhost:5000"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information."
            exit 1
            ;;
    esac
done

# Check if web-app directory exists
if [ ! -d "$WEB_APP_DIR" ]; then
    echo "Error: React web app not found at $WEB_APP_DIR"
    exit 1
fi

cd "$WEB_APP_DIR"

# Install dependencies if node_modules doesn't exist
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

echo "Starting React development server..."
echo "  - Dev server: http://localhost:3000"
echo "  - API proxy: ${API_URL}"
echo ""

# Export API URL for Vite to pick up
export VITE_API_URL="${API_URL}"

npm run dev

