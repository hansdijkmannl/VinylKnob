#!/usr/bin/env python3
"""
Het brein starten op de Pi, bereikbaar vanaf je telefoon en je Mac.

Waarom dit bestand bestaat en er niets in ../brein/ gewijzigd is: server.py
bindt op 127.0.0.1, wat op je Mac precies goed is maar op een headless Pi
betekent dat je er niet bij kunt. En juist die webinterface is waar je de
onherkende platen koppelt — met je telefoon in je hand, naast de platenspeler.

In plaats van server.py aan te passen wordt hier alleen de bindadres-keuze
onderschept. Alle routes, de database en de webinterface komen ongewijzigd uit
../brein/. Wil je dit ooit netter: maak van de host in server.py een instelling
en gooi dit bestand weg.

Let op: hierdoor staat de webinterface open op je hele thuisnetwerk, zonder
wachtwoord. Dat is voor dit apparaat een bewuste afweging — er staat niets
gevoeligers in dan je platenkast — maar zet hem niet door je router heen naar
buiten.
"""

from __future__ import annotations

import pathlib
import sys

BRAIN = pathlib.Path(__file__).resolve().parent.parent / "brein"
sys.path.insert(0, str(BRAIN))

from aiohttp import web                                   # noqa: E402

_run_app = web.run_app


def _run_app_overal(app, **kw):
    kw["host"] = "0.0.0.0"
    return _run_app(app, **kw)


web.run_app = _run_app_overal

import server                                             # noqa: E402

if __name__ == "__main__":
    server.main()
