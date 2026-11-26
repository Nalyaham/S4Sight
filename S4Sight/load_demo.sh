#!/usr/bin/env bash
# Install the bundled DEMO models for TB, stool and STI (trained on computer-drawn pictures only, not for diagnosis).
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Not installed yet. Run ./install.sh first."; exit 1; }
.venv/bin/python manage.py migrate --verbosity 0
exec .venv/bin/python manage.py load_demo "$@"
