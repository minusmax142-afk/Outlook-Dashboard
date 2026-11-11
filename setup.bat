@echo off
setlocal
title Outlook Dashboard setup
cd /d "%~dp0"

rem --- Find Python 3.11+ ----------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo.
    echo  Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/
    echo  and tick "Add python.exe to PATH" during setup. Then double-click start.bat again.
    echo.
    pause
    exit /b 1
)

rem --- Create a private virtual environment on first run -------------------
if not exist ".venv\Scripts\python.exe" (
    echo Setting up for first use. This takes a minute...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
)

rem --- Install / update requirements ----------------------------------------
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :fail

rem --- Desktop / Start menu icons + start automatically at Windows sign-in ----
".venv\Scripts\python.exe" launcher.pyw --install
if errorlevel 1 goto :fail

rem --- Start it now in the background (no window) and open the browser ------
start "" ".venv\Scripts\pythonw.exe" launcher.pyw
echo.
echo  Done. The Outlook Dashboard now starts by itself when you sign in to Windows.
echo  Open it any time with the "Outlook Dashboard" icon on your desktop.
echo  You don't need to run this file again.
timeout /t 6 >nul
goto :eof

:fail
echo.
echo  Setup failed. See the messages above. Check your internet connection and try again.
echo.
pause
exit /b 1
