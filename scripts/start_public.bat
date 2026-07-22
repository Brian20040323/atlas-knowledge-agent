@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set MOCK_MODE=auto
set HOST=0.0.0.0
set COQUI_TOS_AGREED=1

if not exist "tools\cloudflared.exe" (
  echo Downloading cloudflared...
  mkdir tools 2>nul
  powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'tools\cloudflared.exe' -UseBasicParsing"
)

echo [1/2] Starting Atlas on port 8000...
start "Atlas Server" /MIN ".venv\Scripts\python.exe" "data\_boot_lan_server.py"
timeout /t 5 /nobreak >nul

echo [2/2] Starting Cloudflare public tunnel...
echo Keep this window open. Closing it will stop the public URL.
echo After the URL appears, open it and enter the password from .env / data\_public_access.txt
"tools\cloudflared.exe" tunnel --url http://127.0.0.1:8000
pause
