#!/bin/bash
set -e

echo "Running UP to YNAB tests..."

# Change to script directory
cd "$(dirname "$0")/.."

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
    echo "✓ Virtual environment activated"
fi

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Run tests with coverage
echo "Running tests with coverage..."
pytest tests/ -v --tb=short --cov=. --cov-report=term-missing --cov-report=html

echo "✓ Tests completed successfully!"
echo "Coverage report generated in htmlcov/index.html"