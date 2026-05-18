#!/usr/bin/env bash
# One-shot install: Python deps + Vite frontend build.
set -euo pipefail

echo "==> Installing Python dependencies…"
pip install -e .

echo "==> Building frontend…"
cd frontend
npm install
npm run build
cd ..

echo ""
echo "Done. Start the server with:"
echo "  python main.py serve"
echo ""
echo "For frontend hot-reload during development:"
echo "  # Terminal 1: python main.py serve"
echo "  # Terminal 2: cd frontend && npm run dev  (proxy → :8000)"
