# mmwcas-stream

Live streaming of raw ADC frames from the TI cascade radar (MMWCAS-RF-EVM, 4 x AWR2243, on the MMWCAS-DSP-EVM capture
board) to a Windows PC, with a live range-azimuth / range-Doppler map. TI's own flow records to the board's SSD and
copies files afterwards; this tool reads the growing capture files on the board while the radar runs and pushes every
frame over TCP, so the PC sees a 16-RX frame about 4 ms after it was captured.

Verified operating point: 20 ms frame period, 1 chirp loop, 12 TX x 16 RX, 256 samples. About 1 % of frames are lost
on the board itself (writer stalls), none on the PC; 30-minute runs and repeated start/stop cycles are clean.

## Hardware and software

- MMWCAS-RF-EVM + MMWCAS-DSP-EVM (TDA2, SD image 3.7.1, NVMe SSD mounted at /mnt/ssd), one 12 V supply, Ethernet to the PC.
- Windows PC with mmWave Studio 3.0.0.14, MATLAB Runtime R2015aSP1 (32-bit), DFP 2.2.4, Git Bash, Windows PowerShell 5.1,
  Python 3.10 or newer with `requirements.txt`. Details and one-time setup: [INSTALL.md](INSTALL.md).

## Quick start

1. Unzip or clone, edit `config.toml` (IPs, Studio dir, firmware image, Python executable) and run `python -m pytest tests`.
2. Open mmWave Studio and wait for "Matlab Engine Started!" in its Output panel.
3. Power the radar + board on, wait about 3 minutes.
4. `sh tools/connect.sh` (Git Bash, any directory): connects, loads firmware, configures the four devices.
5. `sh tools/stream.sh`: a map window opens, frames arrive about 25 s later and the title says LIVE.
6. `sh tools/stop_stream.sh` stops framing and the board recording; `--close-viewer` also closes the window.
7. `sh tools/stream.sh 0 KEEP_demo1` records the 16-RX frames to `captures/KEEP_demo1/`.
8. `python tools/live_maps.py --replay KEEP_demo1` shows a recording without the radar.
9. Steps 2 to 4 once per boot; repeat 5 and 6 as often as you like.
10. If the map never leaves WAITING, read [KNOWN_ISSUES.md](KNOWN_ISSUES.md) (bad boot) before touching anything.

## Documents

- [INSTALL.md](INSTALL.md): one-time setup of the PC, the board and the Python environment.
- [USAGE.md](USAGE.md): per-boot steps, commands, map keys, the rules that bite.
- [ARCHITECTURE.md](ARCHITECTURE.md): data flow, file layout, frame format, where latency and loss come from.
- [KNOWN_ISSUES.md](KNOWN_ISSUES.md): what goes wrong and what to do.
- [THIRD_PARTY.md](THIRD_PARTY.md): what is derived from TI code; [LICENSE](LICENSE): to be decided.

## Layout

`tools/` PC-side scripts (connect, stream, stop, Studio bridge, listener/mux, viewer, recorder, replay, calibration),
`tda2/` the two scripts that run on the board, `lua/` the Studio scripts (TI-derived template + start/stop),
`cascade_dsp/` the processing chain, `tests/` hardware-free tests, `extras/` diagnostics that are not needed to stream.
