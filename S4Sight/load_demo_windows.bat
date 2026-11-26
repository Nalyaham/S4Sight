@echo off
setlocal
cd /d "%~dp0"
title S4Sight demo model
if not exist ".venv\Scripts\python.exe" (
  echo  S4Sight is not installed yet. Double-click install_windows.bat first.
  pause
  exit /b 1
)
echo.
echo  Installing the DEMO models for TB, stool and STI (trained on computer-drawn pictures only, not for diagnosis)...
".venv\Scripts\python.exe" manage.py migrate --verbosity 0
".venv\Scripts\python.exe" manage.py load_demo
echo.
pause
