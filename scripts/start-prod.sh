#!/bin/bash
set -e

echo "Starting UP to YNAB production environment..."

# Change to script directory
cd "$(dirname "$0")/.."

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "❌ .env file not found. Please create it with your API tokens."
    echo "Use .env.example as a template."
    exit 1
fi

# Validate required environment variables
source .env
required_vars=("UP_API_TOKEN" "YNAB_API_TOKEN" "YNAB_BUDGET_ID" "YNAB_ACCOUNT_ID" "WEBHOOK_URL")

for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo "❌ Required environment variable $var is not set"
        exit 1
    fi
done

# Create data directory if it doesn't exist
mkdir -p data

# Start production environment
echo "Starting production containers..."
docker-compose up --build -d

echo "✓ Production environment started!"
echo ""
echo "Services:"
echo "  - API: http://localhost:5001"
echo "  - Health: http://localhost:5001/health"
echo ""
echo "To view logs: docker-compose logs -f"
echo "To stop: docker-compose down"