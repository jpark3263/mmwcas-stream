-- Loaded into mmWave Studio once per session: mirrors WriteToLog() to a file on the PC and runs scripts under pcall with BEGIN/END markers.
MIRROR_LOG = MIRROR_LOG or nil

function set_mirror_log(path)
    MIRROR_LOG = path
    local f = io.open(path, "a")
    if f then f:write("# harness attached " .. os.date("%Y-%m-%d %H:%M:%S") .. "\n"); f:close() end
end

local function mirror_append(s)
    if MIRROR_LOG then
        local f = io.open(MIRROR_LOG, "a")
        if f then f:write(os.date("%H:%M:%S") .. " " .. tostring(s)); if not tostring(s):match("\n$") then f:write("\n") end; f:close() end
    end
end

if not _orig_WriteToLog then
    _orig_WriteToLog = WriteToLog
    WriteToLog = function(s, color)
        mirror_append(s)
        return _orig_WriteToLog(s, color)
    end
end

function run_logged(path)
    mirror_append("### run_logged BEGIN " .. path)
    local ok, ret = pcall(dofile, path)
    mirror_append("### run_logged END " .. path .. " ok=" .. tostring(ok) .. " ret=" .. tostring(ret))
    return ok, ret
end

WriteToLog("harness.lua loaded (WriteToLog mirrored to " .. tostring(MIRROR_LOG) .. ")\n", "blue")
