#!/usr/bin/env bash
# Start S4Sight so phones on the same Wi-Fi can open it (asks for an access PIN).
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Not installed yet. Run ./install.sh first."; exit 1; }
PIN="${SMEARSIGHT_PIN:-}"
if [ -z "$PIN" ]; then
  echo "Phones on the same Wi-Fi will be able to open S4Sight. Use a private Wi-Fi (WPA2)."
  read -r -p "Access PIN (4 or more digits): " PIN
fi
if [ -z "$PIN" ]; then
  echo "No PIN entered. Starting anyway, but anyone on this Wi-Fi can open the app."
  exec .venv/bin/python run.py --lan "$@"
fi
exec .venv/bin/python run.py --lan --pin "$PIN" "$@"
