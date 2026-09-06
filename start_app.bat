@echo off
title Air Compressor Management
echo ========================================================
echo  Starting Air Compressor Management SCADA System...
echo ========================================================
echo.

:: Check if python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found on your system PATH!
    echo Please install Python 3.11+ from https://python.org
    pause
    exit /b
)

:: Launch application
python run.py

pause
