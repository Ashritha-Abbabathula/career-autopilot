# Start Career Autopilot (Telegram). Run from the career-autopilot folder:  powershell -File scripts/start_bot.ps1
# Keeps running until you close the window or press Ctrl+C. If the laptop sleeps, the bot sleeps too.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONIOENCODING = "utf-8"
$py = "python"
if (Test-Path "C:\Users\jayag\venvs\pingfarm\Scripts\python.exe") { $py = "C:\Users\jayag\venvs\pingfarm\Scripts\python.exe" }
& $py -m ca.check_env
Write-Host ""
Write-Host "First time only: in Telegram open your bot and press Start (or send 'hi'), then send 'help'."
Write-Host "Starting the bot. Press Ctrl+C to stop."
& $py -m ca.run
