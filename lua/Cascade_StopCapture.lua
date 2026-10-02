-- Stops framing on all four devices (slaves first, master last), verifies it with a second StopFrame, then ends the TDA recording. Idempotent.
stop_frame_mode = 0
WriteToLog("Starting Frame Stop sequence...\n", "blue")
rc = 0
for i = 4, 1, -1 do
    if (RadarDevice ~= nil and RadarDevice[i] == 1) then
        local ok1, st1 = pcall(ar1.StopFrame_mult, dev_list[i], stop_frame_mode)
        if (ok1 and st1 == 0) then
            WriteToLog("Device "..i.." : Stop Frame Successful\n", "green")
        else
            WriteToLog("Device "..i.." : frames already stopped (StopFrame status "..tostring(st1)..")\n", "blue")
        end
        RSTD.Sleep(50)
        local ok2, st2 = pcall(ar1.StopFrame_mult, dev_list[i], stop_frame_mode)
        if (ok2 and st2 == 0) then
            WriteToLog("Device "..i.." : Stop Frame Failed (still framing after 2 attempts)\n", "red")
            rc = -5
        else
            WriteToLog("Device "..i.." : verified stopped\n", "green")
        end
    end
end
if (ar1.TDACaptureCard_StopRecord_mult ~= nil) then
    local ok, st = pcall(ar1.TDACaptureCard_StopRecord_mult, 1)
    WriteToLog("TDACaptureCard_StopRecord_mult(1) -> ok="..tostring(ok).." status="..tostring(st).." (-1 = nothing was recording)\n", "blue")
end
WriteToLog("Capture sequence completed...\n", "blue")
return rc
