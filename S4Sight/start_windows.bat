@echo off
setlocal
cd /d "%~dp0"
title S4Sight
if not exist ".venv\Scripts\python.exe" (
  echo  S4Sight is not installed yet. Double-click install_windows.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run.py %*
if errorlevel 1 (
  echo.
  echo  S4Sight stopped with an error. Read the message above.
  pause
)
