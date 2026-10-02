# INSTALL: one-time setup

## PC software (Windows 10/11)

1. mmWave Studio 3.0.0.14 from TI, default directory `C:\ti\mmwave_studio_03_00_00_14`. Put the directory in
   `config.toml` (`studio.dir`); the tool loads `mmWaveStudio\Clients\RtttNetClientController\RtttNetClientAPI.dll` from it.
2. MATLAB Runtime R2015aSP1, version 8.5.1, 32-bit (TI's download link is in the Studio user guide). Without it Studio's
   `Startup.lua` dies before it starts the Lua server, port 2777 never listens, and nothing here can talk to Studio.
3. mmWave DFP 2.2.4 (`mmwave_dfp_02_02_04_00`). The firmware image `firmware\xwr22xx_metaImage.bin` goes into
   `config.toml` (`studio.meta_image`). It is for AWR2243 ES1.1 devices, which is what the MMWCAS-RF-EVM carries.
4. Git for Windows (the scripts are `sh` scripts run from Git Bash) and Windows PowerShell 5.1 (the Studio bridge uses
   TI's .NET Framework DLL, which PowerShell 7 cannot load). Both are on a normal Windows install plus Git.
5. OpenSSH client (Windows feature, `ssh` and `scp` in PATH). The board's old dropbear needs legacy key algorithms;
   `tools/tda2_ssh.sh` passes them.
6. Python 3.10 or newer. Create an environment and install `requirements.txt` (numpy, pyqtgraph, PyQt5, matplotlib, h5py, pytest).
   Put its interpreter in `config.toml` (`pc.python`) unless it is the `python` on your PATH in Git Bash.

## Network

- The PC port on the radar link gets a static address on the board's /24 subnet, no gateway: `pc.ip` in `config.toml`
  (the default there is TI's reference setup). The board's address, `tda.ip`, is fixed in its SD image.
- `ssh root@<tda.ip>` must work without a password once the board has booted (about 60 s after power-on).
- Never unplug the cable, disable the adapter or let the PC sleep while Studio is connected to the board (KNOWN_ISSUES.md).

## Board (MMWCAS-DSP-EVM)

1. SD card: TI's `sdimage_3_7_1.img.xz` (Vision SDK 3.07.01, kernel 4.4.84), written with balenaEtcher or Win32DiskImager.
   The image auto-starts the capture application (`/opt/vision_sdk/apps.out`) at boot. Do not edit anything under `/opt`.
2. SSD: an NVMe drive, ext4, mounted at `/mnt/ssd` (TI's cascade user guide, SSD section, describes the one-time format and
   fstab entry). The capture preallocates 2 GB per device per start; keep at least 20 GB free (`tda.free_gb_min`).
3. Radar: the RF-EVM is powered from the DSP-EVM; one 12 V supply for both. No switches to set.
4. Optional serial console: the FT2232 port, first COM port, 115200 8N1 (`extras/serial_log.py`).
5. Check a new board with `sh extras/board_intake.sh` (read-only): kernel, Vision SDK string, SSD mount, Python 2, nc.

## First run

Set `pc.python` in `config.toml` first: the full path of the interpreter where `requirements.txt` is installed
(connect.sh and stream.sh refuse to start if it cannot import pyqtgraph). Then:
```
cd mmwcas-stream
python -m pytest tests                    # all pass without hardware (the MATLAB parity test skips)
DRY=1 sh tools/connect.sh                 # prints what the real run would do, touches nothing
```
Then follow USAGE.md. The first real `sh tools/connect.sh` after a power-cycle takes about 40 s (firmware download to
four devices) and prints `connected and configured`.

## Updating config.toml

Everything machine-specific is there: IPs, ports, Studio directory and port, firmware image, Python executable, SSD mount,
free-space limit, the capture geometry (samples, chirps, loops, period) and the follower priority. The Lua scripts in
`lua/generated/` are rewritten from `config.toml` on every connect and stream; do not edit them by hand.
