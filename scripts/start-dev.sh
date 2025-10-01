#!/bin/bash
set -e

echo "Starting UP to YNAB development environment..."

# Change to script directory
cd "$(dirname "$0")/.."

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found. Copying from .env.example..."
    cp .env.example .env
    echo "Please edit .env file with your API tokens before running again."
    exit 1
fi

# Create data directory if it doesn't exist
mkdir -p data

# Start development environment
echo "Starting development containers..."
docker-compose -f docker-compose.dev.yml up --build -d

echo "✓ Development environment started!"
echo ""
echo "Services:"
echo "  - API: http://localhost:5001"
echo "  - Health: http://localhost:5001/health"
echo "  - Docs: http://localhost:5001/docs"
echo ""
echo "To view logs: docker-compose -f docker-compose.dev.yml logs -f"
echo "To stop: docker-compose -f docker-compose.dev.yml down"