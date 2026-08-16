@echo off
setlocal
cd /d "%~dp0"

set "PYW="
where pyw >nul 2>&1 && set "PYW=pyw -3"
if not defined PYW (
  where pythonw >nul 2>&1 && set "PYW=pythonw"
)

if defined PYW (
  start "" %PYW% "%~dp0app.py"
  exit /b 0
)

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)

if not defined PY (
  echo Python was not found. Run setup.bat first.
  pause
  exit /b 1
)

%PY% "%~dp0app.py"
if errorlevel 1 pause
