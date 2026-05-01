@echo off
setlocal

set PYTHON_EXE=c:\Users\kdani\Downloads\emdsoftware\paymentapproval\.venv\Scripts\python.exe

if not exist "%PYTHON_EXE%" (
  echo Python virtual environment not found at: %PYTHON_EXE%
  exit /b 1
)

cd /d "%~dp0"
"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean --onefile --windowed --name EMDFactoryPanel factory_local_client.py

echo.
echo Build complete! The results are available in:
echo %~dp0dist\EMDFactoryPanel.exe
endlocal
