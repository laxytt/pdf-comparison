#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --onefile \
    --name PDFDiffStudio \
    --paths src \
    src/pdfdiffstudio/__main__.py

echo ""
echo "Portable macOS app created at: dist/PDFDiffStudio.app"
