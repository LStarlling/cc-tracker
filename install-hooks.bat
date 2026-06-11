@echo off
REM Merge cc-tracker hooks into %USERPROFILE%\.claude\settings.json (idempotent).
REM Run  install-hooks.bat --uninstall  to remove them.
setlocal
pushd "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe plugin\install_hooks.py %*
) else (
  py -3 plugin\install_hooks.py %*
)
popd
pause
