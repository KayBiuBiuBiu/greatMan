#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Please install Python 3.9+." >&2
  exit 1
fi

python3 -m pip install -r requirements.txt
python3 run_tests.py
