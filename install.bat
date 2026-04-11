@echo off
setlocal enabledelayedexpansion
title CatFrens Installer
color 0A

echo.
echo  ============================================================
echo   CatFrens Bot Installer
echo   Hammond Digital Studios
echo  ============================================================
echo.

REM ── Check if Python is installed ─────────────────────────────────────────────
echo  Checking for Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [!!] Python not found on your system.
    echo.
    echo  Please install Python 3.10 or newer from:
    echo  https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: On the installer screen, check the box that says
    echo  "Add Python to PATH" before clicking Install.
    echo.
    echo  After installing Python, run this file again.
    echo.
    pause
    start https://www.python.org/downloads/
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo  [OK] Found: %PYVER%
echo.

REM ── Run the installer ─────────────────────────────────────────────────────────
echo  Starting CatFrens installer...
echo.
python install_catfrens.py

if errorlevel 1 (
    echo.
    echo  [!!] Installation encountered an error.
    echo  Check the output above for details.
    echo.
    pause
    exit /b 1
)

echo.
pause
