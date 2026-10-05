$taskPidFile = Join-Path $PSScriptRoot 'Temp\server.pid'
if (!(Test-Path -LiteralPath $taskPidFile)) { exit 0 }
$taskServerPid = [int](Get-Content -LiteralPath $taskPidFile)
$taskServerProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $taskServerPid"
$taskExpectedPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$taskExpectedScript = Join-Path $PSScriptRoot 'run-local.py'
if ($taskServerProcess -and $taskServerProcess.ExecutablePath -eq $taskExpectedPython -and $taskServerProcess.CommandLine.Contains($taskExpectedScript)) {
    & taskkill.exe /PID $taskServerPid /T /F
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the VK backup server.' }
    Write-Output 'VK backup server stopped.'
} elseif ($taskServerProcess) {
    throw 'The saved PID belongs to another process. Nothing was stopped.'
}
