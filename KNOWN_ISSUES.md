# KNOWN ISSUES

## Bad boot (the lottery)

On some boots the board's capture path delivers no frames: Studio reports every step `Successful`, the capture files
are created at ARM, but nothing is ever written (0 B and deleted at stop, or preallocated and all zeros). Signature:
`stream.sh` prints `LIVE WATCHDOG: ... the TDA is NOT writing frames` and the map stays on WAITING. Seen on two boards,
roughly one boot in three or four, regardless of whether Studio was opened before or after the board. Nothing in the
boot log tells a good boot from a bad one; only the first capture does. Recovery: `sh tools/stop_stream.sh --force`,
power-cycle the board with Studio left open, wait 3 min, `sh tools/connect.sh`, `sh tools/stream.sh`. Within one good
boot every later stream works.

## Software reboot hangs

`reboot` on the board stops at `Restarting system` and never reaches U-Boot (no banner, no ping). Recovery is a
power-cycle only.

## ~1 % frame loss on the board at 20 ms

The capture application stalls for 200 to 220 ms about three times a minute and drops about 10 frames each time, with
or without a reader. At 50 and 100 ms it is lossless. The loss is visible as timestamp jumps in the idx files
(`python tools/capture_stats.py`), never as corrupt frames; the mux keeps frame indices consistent across the gap.

## 10 ms period unsupported

The only 10 ms attempt ended with `Stop Frame Failed` on all four devices and needed a power-cycle. Not retried.

## Stale session after an Ethernet drop

If the PC's link goes down or the PC sleeps while Studio is connected, the board's capture application keeps the dead
TCP session on its control port (single client) and every later ConnectTDA fails with `Not able to connect with the TDA
board` until the board is power-cycled.

## "TDA ARM already done"

Studio still thinks a previous capture is armed (board power-cycled under a live stream). `connect.sh` and `stream.sh`
clear it in their pre-flight (an idempotent stop); if it persists, run `sh tools/connect.sh` again.

## Studio's Lua server accepts one client

It never notices a dead client. Only `tools/studio_bridge.ps1` may connect; `studio_cmd.sh start/stop` manages it and
a new Studio process needs `stop` then `start`. If the server hangs, type `RSTD.NetClose()` then `RSTD.NetStart()` in
Studio's Lua Shell. The client DLL is .NET Framework: the bridge must run under Windows PowerShell 5.1.

## MATLAB Runtime is a hard requirement

Without MATLAB Runtime R2015aSP1 (8.5.1, 32-bit) Studio's `Startup.lua` aborts before `RSTD.NetStart()`, port 2777
never listens and every script here stops with "Studio's Lua server is not listening".

## Other quirks

- Frame limits: `num_frames_to_capture` above a Studio spin-box maximum (9000 rejected, 500 accepted) throws at ARM; the
  tool always uses 0 (no limit) and stops from the script.
- `StopRecord` returns status -1 when the recording already ended by itself; that is not an error.
- The board clock reads 2019 and drifts about 2 ms/min against the PC; latencies over long runs are anchored per minute.
- The board has Python 2.7 only, no `pkill` (use `busybox pkill`), and a `tail -f` that polls once per second.
- Board "free" RAM falls to a few MB during a stream (page cache); `MemAvailable` stays at 2.4 GB. Not a leak.
- After the first file rollover (16384 frames, 5.5 min at 20 ms) the second file grows on demand at 0.6 GB/min.
- Recording adds PC-side jitter (p99 50 ms instead of 27 ms) because the recorder writes on the mux thread.
- The viewer runs uncalibrated until `tools/calibrate.py` has produced `calib.npz` from a corner-reflector recording.
