# MuseGaze × goofi-pipe — real signal processing, live, on your machine

Status: proposal for review. Nothing here changes the current browser-only build until we merge the bridge.

## Why this exists

The current MuseGaze does its DSP inside the browser: Web Bluetooth → FFT → fixed-gain relative band power → visuals. That is fine for a demo but wrong for research:

- **No LSL, no trustworthy timestamps.** Web Bluetooth hands samples with browser-side arrival times, not device clock times. Gaze+EEG work needs a shared clock; that is unreachable from a browser tab (liblsl resolves streams over UDP/TCP multicast, which browsers do not expose).
- **The mapping barely moves.** Visuals track *raw relative* band power. Relative alpha sits near its own mid-range, so eyes-open→closed nudges it and everything else looks dead. We record a baseline (`baseMean`) but never drive the visuals from it.
- **Minimal preprocessing.** No notch, no proper band-pass until recently, no artifact rejection, no per-subject normalization, no separation of oscillatory power from the 1/f aperiodic slope.

goofi-pipe already solves all of this with validated, reviewable nodes. We adopt it as the signal backend and demote MuseGaze to a pure renderer.

## The data flow — all local, Muse live

```
Muse 2  ──BLE──▶  muselsl (or BlueMuse)  ──LSL──▶  goofi-pipe  ──OSC(UDP)──▶  osc_to_ws.py  ──WebSocket──▶  goofi-bridge.html  ──BroadcastChannel('musegaze')──▶  index.html (Visualiser)
         live            LSL EEG stream        node graph / DSP        localhost:9000        localhost:8765            browser tab                     unchanged
```

Every arrow is on one laptop. The only new code we write is `osc_to_ws.py` (bridge) and `goofi-bridge.html` (the page that replaces `control.html` as the driver). The Visualiser (`index.html`) is unchanged — it still listens on `BroadcastChannel('musegaze')` for `{ f:{Delta,Theta,Alpha,Beta,Gamma,...}, spec, ... }`.

Why a bridge at all: goofi can emit OSC / LSL / ZeroMQ, none of which a browser can receive directly. `osc_to_ws.py` receives goofi's OSC on a UDP port and rebroadcasts it as WebSocket JSON, which the browser *can* read.

## The goofi patch (build this in goofi's node GUI)

### Basic (drives the visuals)
1. **EEGRecording** *(only for offline testing)* or skip when using the live headset.
2. **LSLClient** — `stream_name` = the muselsl stream (e.g. `PettalMuse` / `Muse`), `source_type` = `EEG`. This is the live inlet.
3. **Buffer** — window ≈ 1.0–2.0 s, ~75% overlap. Holds the sliding epoch.
4. **Select** — keep the 4 Muse channels (TP9, AF7, AF8, TP10); drop AUX if present.
5. *(filter)* goofi applies band-pass/notch inside PSD/Monolith; for explicit control use **Monolith** (band-pass + notch + DC removal + standardize) or a Math/Function chain. Notch at your mains (50 or 60 Hz).
6. **PSD** — Welch power spectral density per channel.
7. **PowerBandEEG** — δ θ α (low/high) β γ. Use *relative* power.
8. **Reduce** (mean over channels) → one value per band, or keep per-channel for topography later.
9. **Math** — rescale to a display range, but do it against a **baseline z-score**, not a blind 0–1 (see below).
10. **ExtendedTable** — assemble a table: keys `delta, theta, alpha, beta, gamma` (+ optional `spec`).
11. **OscOut** — send that table to `127.0.0.1:9000`. Each key becomes an OSC address (`/delta`, `/alpha`, …).

### Advanced (add as you go)
- **Select → PowerBandEEG → ExtendedTable → OscOut** for per-channel band power (topography, FAA).
- **Connectivity** (wPLI / coherence) and **Spectrogram** (PSD → Buffer) for the richer views.
- **DimensionalityReduction / PCA** on the band vector for a 2–3D state trajectory.
- **Classifier** for on-the-fly state decoding (relaxed / focused / drowsy) once you have labels.
- **specparam / FOOOF** (via Function/Math or a custom node) to separate real oscillatory peaks from the aperiodic 1/f slope — "high alpha" is often just a steeper slope.

## The fix for "I don't see the brainwave do anything"

Map **baseline z-scores**, not raw relative power.

1. Record a 40–60 s baseline (eyes-open rest, then eyes-closed) → per-band mean `μ` and SD `σ`.
2. Live feature `z = (x − μ) / σ`, clip to about ±3, map ±3 → 0..1 for the visuals.
3. Now the *same* physiological change fills the visual range, and it is comparable across people and sessions. goofi's **Math** node does the rescale; feed it `μ`/`σ` from a short calibration (a **Buffer** + **Reduce** over the baseline window, or compute once and store as a **ConstantArray**).

## Gaze integration (why LSL is the point)

Pupil Labs and Tobii publish gaze over LSL natively. Run their LSL relay alongside muselsl and goofi's **LSLClient** can pull both, so EEG and gaze share one clock and you can epoch both to the same events. Record everything with **WriteCsv**/LSL recorder for offline analysis. This is the whole reason to be on LSL rather than browser BLE.

## Honest caveats to keep in the README

Muse 2 = 4 dry electrodes (TP9, AF7, AF8, TP10) at 256 Hz. It supports: eyes-open/closed alpha, drowsiness (theta), coarse frontal-asymmetry valence (FAA), an engagement index (β/(α+θ)). It does **not** support source localization or fine cognitive decoding. Frontal channels are blink/EMG-heavy; "gamma" is largely jaw EMG. Report % of windows rejected for artifact, and normalize per subject.

## Setup (macOS / Apple Silicon)

```bash
# 1. stream the Muse to LSL
pip install muselsl pylsl
muselsl stream            # pairs the Muse, creates an LSL EEG stream

# 2. goofi-pipe
pip install goofi-pipe    # (or clone the repo and pip install -e .)
goofi-pipe                # opens the node GUI; build the patch above

# 3. the bridge (this repo)
pip install python-osc websockets
python tools/osc_to_ws.py   # OSC 127.0.0.1:9000  ->  WebSocket 127.0.0.1:8765

# 4. open the driver page, then the Visualiser
#    goofi-bridge.html  (connects to ws://localhost:8765, feeds BroadcastChannel)
#    index.html         (the Visualiser, unchanged)
```

## Repo layout proposed

```
docs/GOOFI-INTEGRATION.md   <- this file
tools/osc_to_ws.py          <- OSC -> WebSocket bridge
goofi-bridge.html           <- WebSocket -> BroadcastChannel driver (replaces control.html when using goofi)
control.html                <- kept: browser-only fallback (no goofi needed)
index.html                  <- Visualiser, unchanged
```

## Open questions for review

- Mains frequency for the notch (50 vs 60 Hz) at your location.
- Baseline protocol: fixed 60 s at session start, or a rolling 5-min baseline?
- Which gaze hardware (Pupil Labs, Tobii, webcam/WebGazer) — decides the LSL relay.
- Do we want goofi to also stream the raw PSD array so the Spectrum and Plasma views run off goofi too, or keep those browser-side?
