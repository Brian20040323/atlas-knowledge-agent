@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set MOCK_MODE=auto
set HOST=0.0.0.0
set COQUI_TOS_AGREED=1
echo Starting Atlas on http://0.0.0.0:8000 ...
".venv\Scripts\python.exe" "data\_boot_lan_server.py"
pause
