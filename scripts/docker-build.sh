#!/bin/bash
set -e

echo "Building UP to YNAB Docker images..."

# Change to script directory
cd "$(dirname "$0")/.."

# Build production image
echo "Building production image..."
docker build -t up-to-ynab:latest -f Dockerfile .
echo "✓ Production image built: up-to-ynab:latest"

# Build development image
echo "Building development image..."
docker build -t up-to-ynab:dev -f Dockerfile.dev .
echo "✓ Development image built: up-to-ynab:dev"

# Optional: Build with version tag if provided
if [ ! -z "$1" ]; then
    echo "Tagging with version: $1"
    docker tag up-to-ynab:latest up-to-ynab:$1
    echo "✓ Version tag created: up-to-ynab:$1"
fi

echo "✓ Docker build completed successfully!"
docker images | grep up-to-ynab