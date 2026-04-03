@echo off
setlocal EnableExtensions

cd /d "%~dp0"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
  echo [INFO] .venv not found. Creating...
  where python >nul 2>nul
  if "%ERRORLEVEL%"=="0" (
    python -m venv .venv || goto :fatal
  ) else (
    where py >nul 2>nul
    if "%ERRORLEVEL%"=="0" (
      py -3 -m venv .venv || goto :fatal
    ) else (
      echo [ERROR] Python not found in PATH.
      goto :fatal
    )
  )
)

echo [INFO] Checking dependencies...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if not "%ERRORLEVEL%"=="0" goto :fatal

echo [INFO] Starting NeuroKG Desktop V3...
"%PYTHON_EXE%" -m scripts.desktop.run_desktop
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo [ERROR] Desktop exited with code %EXIT_CODE%.
  pause
)
exit /b %EXIT_CODE%

:fatal
echo [ERROR] Failed to start desktop runtime.
pause
exit /b 1
