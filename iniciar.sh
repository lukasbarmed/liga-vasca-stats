#!/usr/bin/env bash
# Linux / macOS: ./iniciar.sh
cd "$(dirname "$0")" || exit 1
command -v python3 >/dev/null || { echo "Necesitas Python 3.10 o superior"; exit 1; }
if [ ! -x .venv/bin/python ]; then
  echo "Preparando entorno (solo la primera vez)..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt waitress || exit 1
fi
exec .venv/bin/python run_local.py
