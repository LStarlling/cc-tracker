@echo off
REM cc-tracker launcher: start the collector server (:8765) + the desktop float.
REM Keep this file ASCII-only (Chinese in .bat garbles under cmd codepage).
setlocal
pushd "%~dp0"

if not exist .venv (
  echo [1/3] Creating virtual environment ...
  py -3 -m venv .venv || goto :err
)

echo [2/3] Installing Python deps ...
.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements.txt || goto :err

echo [3/4] Starting collector (background, minimized window) ...
REM Kill any old collector holding :8765 first, so we start clean (drop stale in-memory
REM session state) and load the latest server code. A second collector can't bind anyway.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do taskkill /f /pid %%p >nul 2>&1
start "cc-tracker collector" /min "%~dp0.venv\Scripts\python.exe" -m server

echo [4/4] Launching desktop float ...
if not exist desktop\node_modules (
  echo   [first run] installing electron, please wait ...
  pushd desktop & call npm install & popd
)
start "" "%~dp0desktop\node_modules\electron\dist\electron.exe" "%~dp0desktop"

echo.
echo ===============================================
echo  Collector + desktop float now run in the background.
echo  Collector: the minimized "cc-tracker collector" window -- close it to stop.
echo  Float: red apple (bottom-right) + tray icon.
echo  Wire Claude Code once with: install-hooks.bat
echo ===============================================
goto :end

:err
echo.
echo [ERROR] setup failed. Need Python 3.9+ (py -3 --version) and Node.js (node -v).
:end
popd
pause
