#!/usr/bin/env python3
"""
osc_to_ws.py  —  MuseGaze × goofi-pipe bridge.

Receives OSC messages from goofi-pipe's OscOut node (band powers etc.) on a local
UDP port and rebroadcasts the latest values as WebSocket JSON, so the browser
Visualiser can consume them (a browser cannot read OSC/UDP or LSL directly).

Flow:  goofi  --OSC/UDP 127.0.0.1:9000-->  this script  --WebSocket 127.0.0.1:8765-->  goofi-bridge.html

goofi setup:  build an ExtendedTable with keys delta/theta/alpha/beta/gamma
(and optionally a `spec` array), feed it to an OscOut node addressed to
127.0.0.1:9000.  Each table key arrives here as an OSC address: /delta /alpha ...

Run:
    pip install python-osc websockets
    python tools/osc_to_ws.py            # defaults below
    python tools/osc_to_ws.py --osc-port 9000 --ws-port 8765
"""
import argparse, asyncio, json, threading
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
import websockets

# latest feature values, updated by OSC, read by the WebSocket loop
STATE = {"Delta": 0.0, "Theta": 0.0, "Alpha": 0.0, "Beta": 0.0, "Gamma": 0.0}
SPEC = []                      # optional PSD array if goofi sends /spec
CLIENTS = set()
LOCK = threading.Lock()

# map OSC addresses (lowercase band names) -> the Visualiser's F keys
BAND_ADDR = {
    "/delta": "Delta", "/theta": "Theta", "/alpha": "Alpha",
    "/beta": "Beta", "/lowbeta": "Beta", "/highbeta": "Beta", "/gamma": "Gamma",
}

def _num(args):
    """OscOut may send a scalar or a short array; reduce to one float."""
    if not args:
        return None
    if len(args) == 1:
        try: return float(args[0])
        except (TypeError, ValueError): return None
    try: return float(sum(args) / len(args))
    except (TypeError, ValueError): return None

def on_band(addr, *args):
    key = BAND_ADDR.get(addr.lower())
    v = _num(args)
    if key is not None and v is not None:
        with LOCK:
            STATE[key] = v

def on_spec(addr, *args):
    global SPEC
    try:
        with LOCK:
            SPEC = [float(a) for a in args]
    except (TypeError, ValueError):
        pass

def on_any(addr, *args):
    # catch-all so unmapped addresses are ignored quietly (goofi sends extras)
    pass

def start_osc(host, port):
    disp = Dispatcher()
    for a in BAND_ADDR:
        disp.map(a, on_band)
    disp.map("/spec", on_spec)
    disp.set_default_handler(on_any)
    server = ThreadingOSCUDPServer((host, port), disp)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[osc] listening on {host}:{port}  (goofi OscOut -> here)")
    return server

async def ws_handler(ws):
    CLIENTS.add(ws)
    print(f"[ws] client connected ({len(CLIENTS)} total)")
    try:
        await ws.wait_closed()
    finally:
        CLIENTS.discard(ws)
        print(f"[ws] client left ({len(CLIENTS)} total)")

async def broadcaster(hz):
    period = 1.0 / hz
    while True:
        if CLIENTS:
            with LOCK:
                msg = json.dumps({"f": dict(STATE), "spec": list(SPEC), "src": "goofi"})
            dead = set()
            for ws in CLIENTS:
                try:
                    await ws.send(msg)
                except Exception:
                    dead.add(ws)
            CLIENTS.difference_update(dead)
        await asyncio.sleep(period)

async def main_async(args):
    start_osc(args.osc_host, args.osc_port)
    async with websockets.serve(ws_handler, args.ws_host, args.ws_port):
        print(f"[ws] serving on ws://{args.ws_host}:{args.ws_port}  (browser connects here)")
        await broadcaster(args.rate)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--osc-host", default="127.0.0.1")
    p.add_argument("--osc-port", type=int, default=9000)
    p.add_argument("--ws-host", default="127.0.0.1")
    p.add_argument("--ws-port", type=int, default=8765)
    p.add_argument("--rate", type=float, default=20.0, help="WebSocket broadcast Hz")
    args = p.parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\n[bridge] stopped")
