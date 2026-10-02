# USAGE

All commands run in Git Bash from any directory; the examples assume the repository root.

## Once per boot

1. Open mmWave Studio first. Wait for `Matlab Engine Started!` in its Output panel.
2. Power the board + radar. Wait about 3 minutes (ssh works after 60 s, the capture application needs longer).
3. `sh tools/connect.sh`: ConnectTDA, SOP reset, power-on, firmware download and the base configuration (about 40 s).
   It prints `connected and configured`. Any `!! FAILED` line: see "Rules that bite".

## Stream

```
sh tools/stream.sh                        # until stop_stream.sh or Ctrl-C, no recording
sh tools/stream.sh 120                    # stops by itself after 120 s
sh tools/stream.sh 0 KEEP_demo1           # records the muxed 16-RX frames to captures/KEEP_demo1/ (9.8 MB/s)
LOOPS=4 PERIOD_MS=50 sh tools/stream.sh   # other geometry (the range-Doppler panel appears when loops > 1)
FLIP=1 sh tools/stream.sh                 # mirror the azimuth axis; BG=0 starts without background subtraction
```
The map window opens first and counts down; frames arrive about 25 s later and the title says LIVE. Each stream
reconfigures the radar (profile, chirps, frame), so `LOOPS` and `PERIOD_MS` can change between streams without connect.sh.

## Stop

```
sh tools/stop_stream.sh                   # stops framing on the four devices (verified) and the board recording
sh tools/stop_stream.sh --close-viewer    # ... and closes the map window (the recording is flushed first)
sh tools/stop_stream.sh --force           # stream.sh is gone (closed terminal): stops the radar directly, clears the lock
```
Ctrl-C in the stream.sh terminal does the same as stop_stream.sh. `Device N : frames already stopped` and
`verified stopped` are normal; only `Stop Frame Failed (still framing after 2 attempts)` is a failure.
Every run leaves its index files and loss statistics in `logs/runs/<capture dir>/` (`python tools/capture_stats.py`).

## Record, replay, convert, calibrate

```
python tools/live_maps.py --replay KEEP_demo1          # the map from a recording, no radar
python tools/replay_capture.py KEEP_demo1              # mux statistics of a recording
python tools/make_capture_from_tda.py <dir with *_0000_data.bin> NAME --loops 1   # SSD capture -> recording
python tools/calibrate.py KEEP_reflector --range 3.0   # corner reflector on boresight at 3 m -> calib.npz
```
`calib.npz` in the repository root is applied automatically by the viewer (checkbox "calibration"); without it the
title says uncalibrated. Never use TI's `calibrateResults_*.mat`: it belongs to TI's board.

## Map window

`b` background subtraction on/off, `f` flip azimuth, `space` freeze, `s` screenshot to `logs/`, `a` range-profile
y-axis autoscale on/off. The dB floor and span boxes set one fixed range (default 40 to 140 dB) for the map colours and the
profile axis. Title bar: frames in / processed per second, mux drops, pipeline ms, calibration state. Azimuth sign: negative
= screen left = the left of a person facing the array (the map is oriented as that person sees it).

## Rules that bite

- Bad boot: Studio says `Start Frame Successful` but the map never leaves WAITING and stream.sh prints
  `LIVE WATCHDOG ... the TDA is NOT writing frames`. Run `sh tools/stop_stream.sh --force`, then power-cycle the board
  with Studio left open, wait 3 min, `sh tools/connect.sh` again. A software reboot of the board does not come back.
- Any `Failed` line from Studio (ConnectTDA, SOP, PowerOn, FW, Start/Stop Frame): stop, power-cycle as above.
- `INVALID INPUT` / `Profile Configuration failed` / `RESP TIMEOUT`: the devices lost their initialisation; one
  `sh tools/connect.sh` usually recovers it, otherwise power-cycle.
- Never unplug or sleep the PC's Ethernet while connected: the board keeps a stale session and every later ConnectTDA
  fails until a power-cycle.
- Do not touch the Studio GUI while connected (PowerOff or Reset there leaves the devices unconfigured). Studio's Lua
  server accepts one client: only the bridge started by these scripts may connect to port 2777.
- SSD: a stream refuses to start below 20 GB free. The next start deletes the previous run's directory once its index
  files are archived under `logs/runs/`; a record name starting with `KEEP_` keeps the SSD original. Clean by hand with
  `python tools/ssd_cleanup.py --dry-run` then without the flag. Nothing else under `/mnt/ssd` is ever touched.
- One viewer at a time: stream.sh refuses while the listener ports are in use (`stop_stream.sh --close-viewer`).
- The nERROR LED on the RF board is lit from power-up until about 2 s after ConnectTDA. That is normal.
