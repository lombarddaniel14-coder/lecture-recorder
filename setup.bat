@echo off
setlocal
cd /d "%~dp0"

echo ===============================================
echo   Lecture Recorder - one-time setup
echo ===============================================
echo.

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)

if not defined PY (
  echo Python was not found on this computer.
  echo.
  echo 1. Go to https://www.python.org/downloads/
  echo 2. Download Python for Windows and run the installer
  echo 3. IMPORTANT: tick "Add python.exe to PATH" on the first screen
  echo 4. When it finishes, run this setup.bat again
  echo.
  pause
  exit /b 1
)

echo Using: %PY%
%PY% --version
echo.

echo Installing the pieces this app needs. This takes a few minutes
echo the first time. Leave the window open.
echo.

%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt

if errorlevel 1 (
  echo.
  echo Something failed while installing. Scroll up to see what.
  echo Most common fix: close this window, right-click setup.bat,
  echo and choose "Run as administrator".
  echo.
  pause
  exit /b 1
)

echo.
echo ===============================================
echo   Setup finished.
echo.
echo   Next: double-click "Launch Lecture Recorder.bat"
echo ===============================================
echo.
pause
