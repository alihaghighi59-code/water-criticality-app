@echo off
setlocal
cd /d "%~dp0"

set "BACKEND_DIR=%~dp0backend"
set "FRONTEND_DIR=%~dp0frontend"
set "API_URL=http://127.0.0.1:5055"
set "UI_URL=http://127.0.0.1:5173"

where py >nul 2>&1
if errorlevel 1 (
  echo Python launcher "py" not found. Install Python or fix PATH.
  pause
  exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
  echo npm not found. Install Node.js or fix PATH.
  pause
  exit /b 1
)

if not exist "%FRONTEND_DIR%\node_modules\" (
  echo Installing frontend dependencies...
  pushd "%FRONTEND_DIR%"
  call npm install
  if errorlevel 1 (
    echo npm install failed.
    popd
    pause
    exit /b 1
  )
  popd
)

echo Starting backend on %API_URL% ...
start "WDN Criticality API" /D "%BACKEND_DIR%" cmd /k py -3 server.py

timeout /t 2 /nobreak >nul

echo Starting frontend on %UI_URL% ...
start "WDN Criticality UI" /D "%FRONTEND_DIR%" cmd /k npm run dev -- --host 127.0.0.1 --port 5173

timeout /t 3 /nobreak >nul
start "" "%UI_URL%"

echo.
echo Backend:  %API_URL%
echo Frontend: %UI_URL%
echo Leave the two server windows open while you use the app.
echo You can close this launcher window.
pause
