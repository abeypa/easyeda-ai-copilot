#!/bin/bash
# EasyEDA AI Copilot — Backend Startup Script
# Starts the local FastAPI server on port 5120

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/backend"

echo "================================================"
echo "  EasyEDA AI Copilot — Local Backend Server"
echo "================================================"
echo ""
echo "Installing dependencies..."
pip install -r requirements.txt --quiet

echo ""
echo "Starting server on http://localhost:5120"
echo "Press Ctrl+C to stop"
echo ""

python -m uvicorn main:app --host 0.0.0.0 --port 5120 --reload
