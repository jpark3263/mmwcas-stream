# extras: diagnostics, not needed to stream

These scripts measured and debugged the streaming path; nothing in `tools/` depends on them. They were ported from the
development tree with the release's file names and config.toml, but have not been re-run on hardware in this form.
`pip install psutil pyserial` for the soak monitor and the serial logger. Contents: `soak.sh` (start/stop cycles + 30-min
+ recording soak), `run_experiment.sh` (a capture with board monitors, clock offsets and latency analysis), `board_intake.sh`
(read-only check of a new board), `serial_log.py` (console logger), `bench_pipeline.py` (DSP timing), `run_ti_parity.m` (MATLAB reference for the parity test).
