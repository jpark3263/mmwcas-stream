# Holds the single client connection to mmWave Studio's Lua server and serves <spool>\<name>.lua requests as <spool>\<name>.rc (Windows PowerShell 5.1).
param(
    [Parameter(Mandatory = $true)][string]$Spool,
    [Parameter(Mandatory = $true)][string]$Dll,
    [Parameter(Mandatory = $true)][string]$Ip,
    [Parameter(Mandatory = $true)][int]$Port
)
$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force $Spool | Out-Null
Remove-Item "$Spool\bridge.stop" -ErrorAction SilentlyContinue
$log = "$Spool\bridge.log"
function L($s) { $line = (Get-Date -Format "HH:mm:ss.fff") + " " + $s; Add-Content -Path $log -Value $line; Write-Output $line }
Add-Type -Path $Dll
$init = [RtttNetClientAPI.RtttNetClient]::Init()
if ($init -ne 0) { L "INIT_FAILED rc=$init"; exit 2 }
$conn = [RtttNetClientAPI.RtttNetClient]::Connect($Ip, $Port)
if ($conn -ne 0) { L "CONNECT_FAILED rc=$conn (Studio open? Lua shell: RSTD.NetClose() then RSTD.NetStart())"; exit 3 }
L "connected to $Ip`:$Port (pid $PID)"
Set-Content -Path "$Spool\bridge.pid" -Value $PID
try {
    while ($true) {
        if (Test-Path "$Spool\bridge.stop") { L "stop requested"; break }
        if (-not [RtttNetClientAPI.RtttNetClient]::IsConnected()) { L "connection lost (Studio closed?)"; break }
        Set-Content -Path "$Spool\bridge.alive" -Value (Get-Date -Format "o")
        $req = Get-ChildItem "$Spool\*.lua" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -First 1
        if ($req -eq $null) { Start-Sleep -Milliseconds 200; continue }
        $name = [System.IO.Path]::GetFileNameWithoutExtension($req.Name)
        $rcPath = "$Spool\$name.rc"; $tmp = "$Spool\$name.rc.tmp"
        $cmds = Get-Content -Path $req.FullName | Where-Object { $_.Trim() -ne "" }
        Remove-Item $req.FullName -Force
        $lines = @()
        foreach ($c in $cmds) {
            L "send [$name]: $c"
            $res = $null
            $rc = [RtttNetClientAPI.RtttNetClient]::SendCommand($c, [ref]$res)
            $resTxt = ""
            if ($res -ne $null) { $resTxt = " result=[" + (($res | ForEach-Object { "$_" }) -join "; ") + "]" }
            $lines += ("RC={0}{1} :: {2}" -f $rc, $resTxt, $c)
            L ("  -> RC=" + $rc + $resTxt)
            if ($rc -ne 0) {
                try { $lines += ("   err: " + [RtttNetClientAPI.RtttNetClient]::GetErrMsg($rc) + " / last: " + [RtttNetClientAPI.RtttNetClient]::GetLastError()) } catch {}
            }
        }
        Set-Content -Path $tmp -Value ($lines -join "`r`n")
        Move-Item -Path $tmp -Destination $rcPath -Force
    }
} finally {
    try { [RtttNetClientAPI.RtttNetClient]::Disconnect() | Out-Null } catch {}
    try { [RtttNetClientAPI.RtttNetClient]::Close() | Out-Null } catch {}
    Remove-Item "$Spool\bridge.alive", "$Spool\bridge.pid" -ErrorAction SilentlyContinue
    L "disconnected, exiting"
}
