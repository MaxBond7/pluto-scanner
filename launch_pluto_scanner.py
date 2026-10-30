"""Desktop launcher for Pluto Scanner.

This file is started by ``launch_pluto_scanner.vbs`` through ``pythonw.exe`` so
double-clicking the Windows shortcut does not leave a console window open.

If no device or simulator was requested explicitly, try to find connected
Plutos and open all distinct USB contexts (or all explicit IP contexts).  If
nothing is found, the normal application fallback opens the synthetic
simulator.  This makes the two-radio drone monitor work from the desktop
shortcut without typing URIs.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

args = [str(arg) for arg in sys.argv[1:]]
explicit_source = any(
    arg == "--sim" or arg.startswith("--device") for arg in args
)
if not explicit_source:
    try:
        from pluto_scanner.devices.pluto import scan_pluto_uris

        uris = scan_pluto_uris()
    except Exception:
        uris = []
    # Prefer direct USB contexts over a network context such as pluto.local.
    # Add every distinct USB Pluto; for Ethernet use all explicit ip: URIs
    # and fall back to pluto.local only when no IP is known.
    usb = sorted({uri for uri in uris if uri.startswith("usb:")})
    ip = sorted({uri for uri in uris if uri.startswith("ip:")})
    if usb:
        chosen = usb
    elif ip:
        chosen = ip
    else:
        chosen = uris[:1]
    for uri in chosen:
        args.extend(["--device", uri])

from pluto_scanner.__main__ import main  # noqa: E402

raise SystemExit(main(args))
