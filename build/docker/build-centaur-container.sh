#!/bin/bash
# Build script for centaur-bullseye Docker container
# This creates a minimal Bullseye container to run the incompatible centaur binary

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE_DIR="${SCRIPT_DIR}/centaur-bullseye"
IMAGE_NAME="dgtcentaurmods/centaur-bullseye"
IMAGE_TAG="latest"
FULL_IMAGE_NAME="${IMAGE_NAME}:${IMAGE_TAG}"

echo "Building Docker image: ${FULL_IMAGE_NAME}"
echo "Dockerfile location: ${DOCKERFILE_DIR}/Dockerfile"

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed or not in PATH"
    echo "Install Docker with: sudo apt-get install docker.io"
    exit 1
fi

# Check if Docker daemon is running
if ! docker info &> /dev/null; then
    echo "Error: Docker daemon is not running"
    echo "Start Docker with: sudo systemctl start docker"
    exit 1
fi

# Build the Docker image
echo "Starting Docker build..."
if docker build -t "${FULL_IMAGE_NAME}" "${DOCKERFILE_DIR}"; then
    echo "Successfully built Docker image: ${FULL_IMAGE_NAME}"
    echo "Image size:"
    docker images "${FULL_IMAGE_NAME}" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
else
    echo "Error: Docker build failed"
    exit 1
fi

