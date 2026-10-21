#!/bin/bash
set -e

echo "Running UP to YNAB tests..."

# Change to repo root
cd "$(dirname "$0")/.."

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    echo "✓ Virtual environment activated"
fi

# Install dependencies
echo "Installing dependencies..."
if command -v uv >/dev/null 2>&1; then
    uv pip install -r requirements-dev.txt
else
    python -m pip install -r requirements-dev.txt
fi

# Run tests with coverage
echo "Running tests with coverage..."
pytest -q --cov --cov-report=term-missing --cov-report=html

echo "✓ Tests completed successfully!"
echo "Coverage report generated in htmlcov/index.html"
