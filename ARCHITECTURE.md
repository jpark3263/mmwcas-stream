# ARCHITECTURE

## Data flow

```
 4 x AWR2243 ──CSI-2──> MMWCAS-DSP-EVM (TDA2)                              Windows PC
   master,              FPGA bridge -> IPU2 capture core                    mmWave Studio (Lua server :2777)
   slave1..3            -> A15 Linux: apps.out writes                         ^  tools/studio_bridge.ps1 (one client)
     ^                     /mnt/ssd/<dir>/<dev>_0000_data.bin (O_DIRECT)      |  tools/studio_cmd.sh <- connect.sh, stream.sh
     |                           |                                            |
   SPI config and start/stop <───┼── Studio <─── TCP :5001 (TDA control) ─────┘
                                 v
                 tda2/follow_slot.py x4  (one per device, polls frame slot k = k * frame_bytes)
                                 │ TCP :5001..5004 (one stream per device, fixed-size frames, no header)
                                 v
                 tools/tcp_tail_listener.py: TcpTailListener x4 -> CascadeFrameMux (pairs the 4 streams by frame index)
                                 │ (idx, cube[16 RX, samples, chirps, loops]) complex64        + CaptureRecorder -> captures/<name>/
                                 v
                 cascade_dsp/pipeline.py: RX reorder -> range FFT -> Doppler FFT -> azimuth FFT (86 channels)
                                 v
                 tools/live_maps.py (pyqtgraph): range-azimuth map, boresight profile, range-Doppler map
```

Control path: the PC never talks to the radar directly. `connect.sh` and `stream.sh` send Lua to mmWave Studio through a
bridge process that holds the single allowed connection to Studio's Lua server; Studio talks to the board's capture
application over TCP and to the four devices over SPI through the board. Studio's own capture script sleeps for the whole
capture and blocks every other command, so this tool uses its own start script (arm + start frame, then return) and stop
script (stop frame on the slaves, then the master, each verified by a second stop that must be refused).

## Files on the SSD

One directory per stream, `mmwcas_<name>_<YYYYmmdd_HHMMSS>`, four data files `<dev>_0000_data.bin` plus matching
`<dev>_0000_idx.bin`. The capture is armed with one preallocated file per device (2 146 435 072 bytes, fixed from the start;
unwritten space reads as zeros); after 16384 frames apps.out continues in `<dev>_0001_data.bin`, which grows on demand.
Frame k of a device sits at byte offset k x frame_bytes, written as one O_DIRECT write; dropped radar frames leave no hole,
they only show as a jump in the idx timestamps. The idx file (24-byte header `bckt`, then one 48-byte record per frame with
frame size, a microsecond timestamp on the Vision SDK timer and the byte offset) is written once, when the recording
stops, so it cannot drive live streaming; `tools/parse_idx.py` reads it afterwards for loss statistics.

Without preallocation the capture stops by itself after 0.1 to 1.6 s at periods below 100 ms; with preallocation it runs
indefinitely. That is why the follower reads slots: it peeks at the last 4 KB of slot k until it is non-zero, reads the
slot, re-reads while it still contains a 4 KB run of zeros (write in flight), sends it, and moves to k + 1. It runs at
nice 0 with idle I/O class; at nice 19 it is starved by the capture application and journald, which keep both A15 cores busy.

## Frame format

Per device and frame: `samples x chirps_per_loop x loops x 4 RX x 2 (I,Q) x 2 bytes`, little-endian int16 (TI's reader
takes uint16 and moves the sign from bit 16), I/Q interleaved, RX fastest, then samples, chirps, loops. 256 samples x 12
chirps x 1 loop = 49 152 bytes per device, 196 608 bytes per 16-RX frame, 9.8 MB/s at 20 ms. The mux reshapes each
device to `[4 RX, samples, chirps, loops]` in column-major order and concatenates master, slave1, slave2, slave3 along RX
(file order). The DSP then applies TI's `TI_Cascade_RX_ID` to get the physical RX order; chirp c of the 12-chirp loop
enables TI TX number 12 - c (one TX per chirp, read from the Lua chirp table and asserted in the tests). The processing
chain matches TI's MATLAB example to float precision (MATLAB's `hanning` without zero end points, c = 3e8, range FFT 256,
Doppler FFT over loops, azimuth FFT 256 over the 86 elevation-0 virtual channels at zero Doppler).

## Latency and loss

Measured at 20 ms / 1 loop over 30 minutes: median end-to-end latency (capture timestamp to muxed frame on the PC)
3 to 4 ms, p90 about 13 ms, maxima of 0.3 to 0.8 s during board flush stalls. Loss happens only on the board: the
capture application stalls for 200 to 220 ms about three times a minute and drops about 10 frames each time (about 1 %),
with or without a reader; every frame it writes reaches the PC and the mux. The PC side drops a 16-RX set only when one
device's part is more than 0.25 s late (`mux drops` in the title), and the viewer drops frames only when the DSP falls
behind (`backlog drops`). Bandwidth: 157 Mbit/s at 20 ms / 1 loop against a measured TCP ceiling of about 600 Mbit/s
from the board; 2 loops at 20 ms or 4 loops at 50 ms fit, 4 loops at 20 ms does not. 10 ms periods are not supported
(the capture application fails to stop cleanly). The 1-loop DSP chain takes about 3 ms per frame on a laptop.

## What is and is not real-time

The capture is armed once per stream with a fixed frame size, and the followers, mux and DSP are sized from it.

| change | while framing? | how | takes effect |
|---|---|---|---|
| TX power back-off, RX gain, HPF corners, slope, start frequency, idle and ADC start time | yes | `ar1.ProfileConfig_mult` (dynamic profile update; samples and sample rate excluded) | next frame |
| TX enable set or profile index per chirp | yes | dynamic chirp APIs (`DynChirpCfgSet_mult` + enable) | next frame, after the enable |
| per-chirp TX phase shifters | yes | `DynPerChirpPhShifterCfgSet_mult` | next frame |
| ADC samples, sample rate, chirps per frame, loops, frame period | no | Stop Frame, reconfigure, re-arm (`stream.sh` does this) | next stream |

The four devices receive commands one after another through Studio (about 0.25 s per device per API), so a live change
lands on different frames per device; closed-loop updates through Studio run at roughly 0.5 to 1 Hz. Frame-config APIs
are refused while framing (`API IS ISSUED WHEN FRAMES ARE ONGOING`).
