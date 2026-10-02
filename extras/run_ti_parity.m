% Runs TI's cascade MATLAB chain (unmodified, from the mmWave Studio install) on one frame of a 128-loop capture and saves the
% intermediate arrays for tests/test_parity_matlab.py. Needs MATLAB and the capture (<dev>_0000_data.bin + idx) in
% <repo>/validation/home_far_run/. Set the environment variable MMWCAS_STUDIO_DIR if Studio is not in the default install dir.
%   matlab -batch "cd('<repo>/extras'); run_ti_parity"
frameIdx = 2;
here = fileparts(mfilename('fullpath'));
repo = fileparts(here);
outDir = fullfile(repo, 'validation');
studioDir = getenv('MMWCAS_STUDIO_DIR');
if isempty(studioDir), studioDir = 'C:\ti\mmwave_studio_03_00_00_14'; end
tiRoot = fullfile(studioDir, 'mmWaveStudio', 'MatlabExamples', '4chip_cascade_MIMO_example');
setenv('CASCADE_SIGNAL_PROCESSING_CHAIN_MIMO', tiRoot);
addpath(genpath(fullfile(tiRoot, 'modules'))); addpath(genpath(fullfile(tiRoot, 'main')));
addpath(fullfile(tiRoot, 'utils', 'math')); addpath(fullfile(tiRoot, 'utils', 'dataParse')); addpath(fullfile(tiRoot, 'utils', 'disp'));
dataFolder = fullfile(outDir, 'home_far_run', filesep);
calibFile = fullfile(tiRoot, 'main', 'cascade', 'input', 'calibrateResults_dummy.mat');
pathGenParaFile = fullfile(outDir, 'home_far_run_param.m');

fid = fopen(pathGenParaFile, 'w');
fprintf(fid, 'ADVANCED_FRAME_CONFIG = 0; \n');
fprintf(fid, 'dataPlatform = ''TDA2''; \n');
fprintf(fid, 'numADCSample = 256; \n');
fprintf(fid, 'adcSampleRate = 8e6; \n');
fprintf(fid, 'startFreqConst = 77e9; \n');
fprintf(fid, 'chirpSlope = 78.986e12; \n');
fprintf(fid, 'chirpIdleTime = 5e-6; \n');
fprintf(fid, 'adcStartTimeConst = 6e-6; \n');
fprintf(fid, 'chirpRampEndTime = 40e-6; \n');
fprintf(fid, 'framePeriodicty = 0.1; \n');
fprintf(fid, 'NumDevices = 4; \n');
fprintf(fid, 'frameCount = 9; \n');
fprintf(fid, 'numChirpsInLoop = 12; \n');
fprintf(fid, 'nchirp_loops = 128; \n');
fprintf(fid, 'numTxAnt = 12; \n');
fprintf(fid, 'TxToEnable = [12 11 10 9 8 7 6 5 4 3 2 1]; \n');
fprintf(fid, 'numRxToEnable = 16; \n');
fprintf(fid, 'centerFreq = %d; \n', 77 + 256/8000*78.986/2);
S = load(calibFile); pc = S.params;
fprintf(fid, 'Slope_calib = %d; \n', pc.Slope_MHzperus*1e12);
fprintf(fid, 'fs_calib = %d; \n', pc.Sampling_Rate_sps);
fidC = fopen(fullfile(tiRoot, 'main', 'cascade', 'paramGen', 'module_param.m'));
for ii = 1:32, fgets(fidC); end
tline = fgets(fidC);
while ischar(tline), fwrite(fid, tline); tline = fgets(fidC); end
fclose(fidC); fclose(fid);
addpath(outDir);

load(calibFile);
calibrationObj = calibrationCascade('pfile', pathGenParaFile, 'calibrationfilePath', calibFile);
rangeFFTObj    = rangeProcCascade('pfile', pathGenParaFile);
DopplerFFTObj  = DopplerProcClutterRemove('pfile', pathGenParaFile);
detectionObj   = CFAR_CASO('pfile', pathGenParaFile);
DOAObj         = DOACascade('pfile', pathGenParaFile);
[fileIdx_unique] = getUniqueFileIdx(dataFolder);
[fileNameStruct] = getBinFileNames_withIdx(dataFolder, fileIdx_unique{1});
calibrationObj.binfilePath = fileNameStruct;
calibrationObj.frameIdx = frameIdx;
adcData = datapath(calibrationObj);
adcData = adcData(:, :, calibrationObj.RxForMIMOProcess, :);
rangeFFTOut = []; DopplerFFTOut = [];
for i_tx = 1:size(adcData, 4)
    rangeFFTOut(:, :, :, i_tx)   = datapath(rangeFFTObj, adcData(:, :, :, i_tx));
    DopplerFFTOut(:, :, :, i_tx) = datapath(DopplerFFTObj, rangeFFTOut(:, :, :, i_tx));
end
DopplerFFTOut = reshape(DopplerFFTOut, size(DopplerFFTOut, 1), size(DopplerFFTOut, 2), size(DopplerFFTOut, 3) * size(DopplerFFTOut, 4));
sig_integrate = 10 * log10(sum((abs(DopplerFFTOut)).^2, 3) + 1);
antenna_azimuthonly = detectionObj.antenna_azimuthonly;
X = DopplerFFTOut(:, :, antenna_azimuthonly);
radar_data_angle_range = fft(X, 256, 3);
ra_static = fftshift(squeeze(abs(radar_data_angle_range(:, size(X, 2) / 2 + 1, :))), 2);
[mag_data_static, mag_data_dynamic, y_axis, x_axis] = plot_range_azimuth_2D(detectionObj.rangeBinSize, DopplerFFTOut, ...
    length(calibrationObj.IdTxForMIMOProcess), length(calibrationObj.RxForMIMOProcess), antenna_azimuthonly, 1, 1, 0, 5, 20);
detection_results = [];
angleEst = [];
try
    detection_results = datapath(detectionObj, DopplerFFTOut);
    if ~isempty(detection_results), angleEst = datapath(DOAObj, detection_results); end
catch e
    disp(['detection/DOA skipped: ' e.message]);
end
nDet = length(detection_results);
run(pathGenParaFile);
adcData_tx1 = single(adcData(:, :, :, 1));
rangeFFTOut = single(rangeFFTOut);
DopplerFFTOut = single(DopplerFFTOut);
TI_RX_ID = TI_Cascade_RX_ID;
outFile = fullfile(outDir, sprintf('ti_home_far_run_frame%d.mat', frameIdx));
save(outFile, 'frameIdx', 'adcData_tx1', 'rangeFFTOut', 'DopplerFFTOut', 'sig_integrate', 'ra_static', 'mag_data_static', ...
    'D', 'antenna_azimuthonly', 'overlapAntenna_ID', 'TxToEnable', 'TI_RX_ID', 'rangeBinSize', 'velocityBinSize', ...
    'd_optimal', 'centerFreq', 'nDet', 'detection_results', 'angleEst', '-v7.3');
fprintf('saved %s\n', outFile);
