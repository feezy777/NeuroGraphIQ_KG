@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "HOST=127.0.0.1"
set "PORT=8899"
set "URL=http://%HOST%:%PORT%"
set "FORCE_RESTART=0"
if /I "%~1"=="/restart" set "FORCE_RESTART=1"

if "%FORCE_RESTART%"=="1" (
  echo [INFO] Force restart enabled. Stopping existing process on port %PORT%...
  call :kill_running
)

call :already_running
if "%ERRORLEVEL%"=="0" (
  echo [INFO] NeuroKG Workbench is already running on %URL%
  start "" "%URL%"
  exit /b 0
)

call :ensure_venv
if not "%ERRORLEVEL%"=="0" goto :fatal

echo [INFO] Starting NeuroKG Workbench on %URL%
start "" "%URL%"
"%PYTHON_EXE%" -m scripts.ui.run_dashboard
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo [ERROR] Workbench exited with code %EXIT_CODE%.
  pause
)

exit /b %EXIT_CODE%

:fatal
set "EXIT_CODE=%ERRORLEVEL%"
echo [ERROR] Workbench startup failed with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%

:already_running
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  if not "%%P"=="0" exit /b 0
)
exit /b 1

:kill_running
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  if not "%%P"=="0" (
    taskkill /PID %%P /F >nul 2>nul
  )
)
timeout /t 1 >nul
exit /b 0

:ensure_venv
if exist "%PYTHON_EXE%" (
  "%PYTHON_EXE%" -c "import sys" >nul 2>nul && goto :ensure_deps
  echo [WARN] Existing .venv is broken. Recreating...
) else (
  echo [WARN] .venv not found. Creating...
)

if exist ".venv" (
  rmdir /s /q ".venv" >nul 2>nul
  if exist ".venv" (
    echo [ERROR] Cannot remove .venv. Close running Python/Workbench processes and retry.
    exit /b 3
  )
)

call :create_venv
if not "%ERRORLEVEL%"=="0" exit /b %ERRORLEVEL%

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Failed to create virtual environment.
  exit /b 3
)

goto :ensure_deps

:create_venv
where python >nul 2>nul
if "%ERRORLEVEL%"=="0" (
  python -m venv .venv && exit /b 0 || exit /b 5
)

where py >nul 2>nul
if "%ERRORLEVEL%"=="0" (
  py -3 -m venv .venv && exit /b 0 || exit /b 5
)

echo [ERROR] No Python launcher found in PATH.
echo Install Python 3.10+ and ensure "python" or "py" is available.
exit /b 2

:ensure_deps
call :check_imports
if "%ERRORLEVEL%"=="0" goto :venv_ok

echo [WARN] Missing or broken dependencies. Installing requirements...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if not "%ERRORLEVEL%"=="0" (
  echo [WARN] pip install requirements failed. Trying forced repair...
  goto :force_repair
)

call :check_imports
if "%ERRORLEVEL%"=="0" goto :venv_ok

:force_repair
"%PYTHON_EXE%" -m pip install --upgrade --force-reinstall --no-cache-dir Flask PyYAML pandas psycopg2-binary
if not "%ERRORLEVEL%"=="0" (
  echo [ERROR] Failed to repair dependencies automatically.
  exit /b 4
)

call :check_imports
if not "%ERRORLEVEL%"=="0" (
  echo [ERROR] Dependency check still failed after repair.
  exit /b 4
)

:venv_ok
exit /b 0

:check_imports
"%PYTHON_EXE%" -c "import flask, yaml, pandas, psycopg2" >nul 2>nul
exit /b %ERRORLEVEL%
