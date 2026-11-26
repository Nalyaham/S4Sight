"""Start SmearSight.   python run.py            (this computer only)
                      python run.py --lan      (also reachable from phones on the same Wi-Fi; set a PIN first)"""
import argparse
import os
import socket
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--lan", action="store_true", help="listen on all network interfaces")
ap.add_argument("--port", type=int, default=8000)
ap.add_argument("--pin", default="", help="access PIN (or set SMEARSIGHT_PIN)")
a = ap.parse_args()
if a.pin:
    os.environ["SMEARSIGHT_PIN"] = a.pin

import uvicorn  # noqa: E402

host = "0.0.0.0" if a.lan else "127.0.0.1"
print("\n  SmearSight is starting.")
print(f"  On this computer:  http://localhost:{a.port}")
if a.lan:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); ip = s.getsockname()[0]; s.close()
        print(f"  On phones (same Wi-Fi):  http://{ip}:{a.port}")
    except Exception:
        print("  Find this computer's Wi-Fi address and open http://<address>:%d on the phone." % a.port)
    if not os.environ.get("SMEARSIGHT_PIN"):
        print("\n  WARNING: no access PIN is set. Anyone on this network can open the app.")
        print("  Restart with:  python run.py --lan --pin 1234\n")
uvicorn.run("app.main:app", host=host, port=a.port, log_level="warning")
