@echo off
setlocal
cd /d "%~dp0"
title S4Sight (phones on Wi-Fi)
if not exist ".venv\Scripts\python.exe" (
  echo  S4Sight is not installed yet. Double-click install_windows.bat first.
  pause
  exit /b 1
)
echo.
echo  S4Sight for phones
echo  ---------------------
echo  Phones on the same Wi-Fi will be able to open S4Sight.
echo  Choose an access PIN (4 or more digits). Everyone who uses the app types it once on each phone.
echo  Use a private Wi-Fi (WPA2), not a public or guest network.
echo.
set "PIN=%SMEARSIGHT_PIN%"
if not defined PIN set /p "PIN=  Access PIN: "
if not defined PIN (
  echo  No PIN entered. Starting anyway, but anyone on this Wi-Fi can open the app.
  ".venv\Scripts\python.exe" run.py --lan %*
) else (
  ".venv\Scripts\python.exe" run.py --lan --pin "%PIN%" %*
)
if errorlevel 1 (
  echo.
  echo  S4Sight stopped with an error. Read the message above.
  pause
)
