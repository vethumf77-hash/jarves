# Creates a "Jarvis" shortcut on your Desktop (and in the Start menu) that opens the app
# with one click and no console window. Run it via create_shortcut.bat.
$app = $PSScriptRoot
$py  = Join-Path $app "venv\Scripts\pythonw.exe"

if (-not (Test-Path $py)) {
    Write-Host ""
    Write-Host "Couldn't find $py" -ForegroundColor Red
    Write-Host "This script expects the virtual environment from the README (a folder named 'venv'"
    Write-Host "inside the Jarvis folder). Set that up first, then run this again."
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$targets = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "Jarvis.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "Jarvis.lnk")
)
foreach ($path in $targets) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath       = $py
    $lnk.Arguments        = '"' + (Join-Path $app "app.py") + '"'
    $lnk.WorkingDirectory = $app
    $lnk.IconLocation     = (Join-Path $app "jarvis.ico")
    $lnk.Description      = "Jarvis voice assistant"
    $lnk.Save()
    Write-Host "Created $path" -ForegroundColor Green
}
Write-Host ""
Write-Host "Done. Double-click 'Jarvis' on your Desktop to start it."
Write-Host "(Tip: right-click it and choose 'Pin to taskbar' to keep it one click away.)"
