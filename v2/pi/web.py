#!/usr/bin/env python3
"""
Start the brain on the Pi, reachable from your phone.

Why this file exists and nothing in ../brain/ was changed: server.py binds to
127.0.0.1, which is right on a laptop but on a headless Pi means you cannot
reach it. And that web interface is precisely where you link the records it
could not place — phone in hand, standing at the turntable.

Rather than modify server.py, this intercepts only the choice of bind address.
Every route, the database and the web interface come unchanged from ../brain/.
If you ever want it tidier: make the host a setting in server.py and delete this
file.

Note that this leaves the web interface open on your whole network, with no
password. For this device that is a deliberate trade-off — there is nothing in
it more sensitive than your record collection — but do not forward it through
your router.
"""

from __future__ import annotations

import pathlib
import sys

BRAIN = pathlib.Path(__file__).resolve().parent.parent / "brain"
sys.path.insert(0, str(BRAIN))

from aiohttp import web                                   # noqa: E402

_run_app = web.run_app


def _run_app_everywhere(app, **kw):
    kw["host"] = "0.0.0.0"
    return _run_app(app, **kw)


web.run_app = _run_app_everywhere

import server                                             # noqa: E402

if __name__ == "__main__":
    server.main()
