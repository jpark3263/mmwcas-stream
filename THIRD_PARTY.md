# THIRD_PARTY

Parts of this repository are derived from Texas Instruments example code shipped with mmWave Studio 3.0.0.14 and the
mmWave DFP 2.2.4. That code is licensed under TI's "MMWAVE Evaluation, Development and Demonstration Software License
Agreement" (`C:\ti\mmwave_studio_03_00_00_14\license.txt`, manifest `mmwave_studio_manifest.html`). The derived files
below remain subject to those terms; no TI file is copied verbatim into this repository, and TI's firmware, SD images,
DLLs and MATLAB files are referenced by their paths in the TI installs instead.

Paths below are relative to `C:\ti\mmwave_studio_03_00_00_14\mmWaveStudio\`.

| file here | derived from | what was taken |
|---|---|---|
| `lua/Cascade_Configuration_MIMO.template.lua` | `Scripts\Cascade\Cascade_Configuration_MIMO.lua` | the whole configuration sequence; IP, firmware path, loops, frame count and period made into placeholders |
| `lua/Cascade_StartCapture.template.lua`, `lua/Cascade_StopCapture.lua` | `Scripts\Cascade\Cascade_Capture.lua` | the ARM / start-frame / stop-frame / stop-record calls, split into a start script and a verified stop script |
| `cascade_dsp/geometry.py` | `MatlabExamples\4chip_cascade_MIMO_example\main\cascade\paramGen\module_param.m` | antenna position tables, RX id map, design frequency, virtual array, overlap table, azimuth-only channel set |
| `cascade_dsp/pipeline.py` | `modules\rangeProc\@rangeProcCascade`, `modules\DopplerProc\@DopplerProcClutterRemove`, `utils\disp\plot_range_azimuth_2D.m`, `modules\DOA\@DOACascade\DOA_beamformingFFT_2D.m`, `utils\dataParse\read_ADC_bin_TDA2_separateFiles.m` | the processing chain (DC removal, window, FFT sizes, axis formulas, TDM Doppler compensation, 2-D DOA FFT) and the ADC file layout |
| `cascade_dsp/calibration.py` | `modules\calibration\@calibrationCascade`, `@genCalibrationMatrixCascade` (incl. `radar_fft_find_peak.m`), `utils\math\Average_Ph.m`, `main\cascade\cascade_MIMO_antennaCalib.m` | per-channel correction and its generation from a reflector capture |
| `tools/tcp_tail_listener.py` (`device_frame_to_cube`) | `utils\dataParse\read_ADC_bin_TDA2_separateFiles.m` | the per-device reshape and sign convention |
| `extras/run_ti_parity.m` | runs TI's chain unmodified | writes a reference `.mat` for the parity test; the generated parameter file copies the tail of `module_param.m` |
| `tools/studio_bridge.ps1` | `Clients\RtttNetClientController\RtttNetClientAPI.dll` (loaded at run time, not copied) | the Lua command client |

The firmware image `xwr22xx_metaImage.bin` (DFP 2.2.4) and the board SD image `sdimage_3_7_1.img.xz` are TI
deliverables obtained from TI; they are not part of this repository.

Everything else in the repository is original work; its license is stated in `LICENSE`.
