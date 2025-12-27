#!/bin/bash
# scripts/run-react.sh
#
# Starts the React web app development server.
# Proxies API calls to the Flask backend at localhost:5000.
#
# Usage:
#   ./scripts/run-react.sh
#
# Prerequisites:
#   - Node.js and npm installed
#   - Flask backend running on port 5000 (run scripts/run-web.sh first)
#

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
WEB_APP_DIR="${REPO_ROOT}/src/universalchess/web-app"

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
echo "  - API proxy: http://localhost:5000"
echo ""
echo "Make sure the Flask backend is running (scripts/run-web.sh)"
echo ""

npm run dev

