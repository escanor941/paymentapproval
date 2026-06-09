@echo off
:: ============================================================
::  Build EMD Factory Panel Installer
::  Step 1: Builds the EXE with PyInstaller
::  Step 2: Packages it into a Windows installer with Inno Setup
::
::  Requirements:
::    - Python venv at .venv\ (run once: python -m venv .venv)
::    - PyInstaller (already installed in .venv)
::    - Inno Setup 6: https://jrsoftware.org/isdl.php
:: ============================================================

setlocal

set PYTHON_EXE=.venv\Scripts\python.exe
set ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe

if not exist "%ISCC_PATH%" set ISCC_PATH=C:\Program Files\Inno Setup 6\ISCC.exe
if not exist "%ISCC_PATH%" set ISCC_PATH=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC_PATH%" (
    echo.
    echo  ERROR: Inno Setup 6 not found.
    echo  Download and install from: https://jrsoftware.org/isdl.php
    echo.
    pause
    exit /b 1
)

echo.
echo  [1/2] Building EMDFactoryPanel.exe with PyInstaller...
echo  ------------------------------------------------------
"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean --onefile --windowed --name EMDFactoryPanel factory_local_client.py
if errorlevel 1 (
    echo.
    echo  ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

echo.
echo  [2/2] Creating Windows installer with Inno Setup...
echo  ----------------------------------------------------
"%ISCC_PATH%" setup_factory.iss
if errorlevel 1 (
    echo.
    echo  ERROR: Inno Setup compile failed.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo   SUCCESS!
echo   Installer: installer\EMDFactoryPanel_Setup_v1.1.exe
echo  ============================================================
echo.
pause