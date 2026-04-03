@echo off
setlocal

cd /d "%~dp0"

echo === NeuroKG Workbench Diagnose ===
echo [1] Check port 8899
netstat -ano | findstr :8899
echo.

echo [2] Check .venv python
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; print(sys.executable); print(sys.version)" 2>nul
  if not "%ERRORLEVEL%"=="0" (
    echo .venv python is broken
  )
) else (
  echo .venv\Scripts\python.exe missing
)
echo.

echo [3] Check dashboard script import
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import scripts.ui.dashboard; print('dashboard import ok')" 2>nul
  if not "%ERRORLEVEL%"=="0" (
    echo dashboard import failed
  )
)
echo.
echo === End ===
pause

