-- Arms the TDA capture (one preallocated file per device) and starts framing, then returns so Studio stays responsive; stop with Cascade_StopCapture.lua.
n_files_allocation              =   1
data_packaging                  =   0
capture_directory               =   "__CAPTURE_DIRECTORY__"
num_frames_to_capture           =   0

WriteToLog("Starting TDA ARM...\n", "blue")
status = ar1.TDACaptureCard_StartRecord_mult(1, n_files_allocation, data_packaging, capture_directory, num_frames_to_capture)
if (status == 0) then
    WriteToLog("TDA ARM Successful\n", "green")
else
    WriteToLog("TDA ARM Failed\n", "red")
    return -5
end
RSTD.Sleep(1000)
WriteToLog("Starting Frame Trigger sequence...\n", "blue")
for i = 4, 1, -1 do
    if (RadarDevice[i] == 1) then
        if (0 == ar1.StartFrame_mult(dev_list[i])) then
            WriteToLog("Device "..i.." : Start Frame Successful\n", "green")
        else
            WriteToLog("Device "..i.." : Start Frame Failed\n", "red")
            return -5
        end
    end
end
WriteToLog("Capturing AWR device data to the TDA SSD (streaming; stop with Cascade_StopCapture.lua)...\n", "blue")
return 0
