@echo on
setlocal EnableDelayedExpansion
title Trakt2EmbySync Setup
color 0A
echo Trakt2EmbySync Setup
echo ==================
echo.

:: Create a log file
echo Setup started at %date% %time% > setup_log.txt

:: Add pause at the beginning so user can see any errors
echo Setting up Trakt2EmbySync. This window will show progress...
echo If the window closes immediately, try running as administrator.
echo.
echo Press any key to begin setup...
pause > nul

:: Check if Python is installed
echo Checking for Python installation...
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed. Please install Python 3.8 or higher. >> setup_log.txt
    echo Python is not installed or not found in PATH.
    echo Please install Python 3.8 or higher from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    echo Press any key to exit...
    pause > nul
    exit /b %errorlevel%
)

:: Show Python version
echo Found Python:
python --version

:: Check if virtual environment already exists
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv >> setup_log.txt 2>&1
    if %errorlevel% neq 0 (
        echo ERROR: Failed to create virtual environment. >> setup_log.txt
        echo Failed to create virtual environment.
        echo This might be due to missing Python components or permissions.
        echo Try running this script as administrator.
        echo.
        echo Press any key to exit...
        pause > nul
        exit /b %errorlevel%
    )
) else (
    echo Virtual environment already exists.
)

:: Activate virtual environment and install requirements
echo.
echo Activating virtual environment and installing requirements...
echo This may take a few minutes...

:: Check if virtual environment exists
if not exist .venv\Scripts\activate.bat (
    echo ERROR: Virtual environment activation script not found. >> setup_log.txt
    echo Virtual environment activation script not found.
    echo The virtual environment may be corrupted. 
    echo Try deleting the .venv folder and running setup again.
    echo.
    echo Press any key to exit...
    pause > nul
    exit /b 1
)

:: Try to activate the virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo ERROR: Failed to activate virtual environment. >> setup_log.txt
    echo Failed to activate virtual environment.
    echo Try running this script as administrator.
    echo.
    echo Press any key to exit...
    pause > nul
    exit /b %errorlevel%
)

:: Update pip
echo Updating pip...
python -m pip install --upgrade pip >> setup_log.txt 2>&1
if %errorlevel% neq 0 (
    echo WARNING: Failed to update pip. Continuing with installation... >> setup_log.txt
    echo WARNING: Failed to update pip. Continuing with installation...
)

:: Install requirements
echo Installing required packages...
pip install -r requirements.txt >> setup_log.txt 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Failed to install requirements. >> setup_log.txt
    echo Failed to install requirements.
    echo Check setup_log.txt for details.
    echo.
    echo Press any key to exit...
    pause > nul
    exit /b %errorlevel%
)

:: Success message before launching
echo.
echo ✓ Setup completed successfully!
echo ✓ Starting Trakt2EmbySync application...
echo.
echo NOTE: When the web interface opens, go to the Settings tab first
echo to configure your Trakt and Emby connection details.
echo.
echo Press any key to launch the application...
pause > nul

:: Run the app
echo Starting application... >> setup_log.txt
streamlit run app.py
set APP_EXIT_CODE=%errorlevel%

:: If the app exits or fails to start, keep the window open
echo.
if %APP_EXIT_CODE% neq 0 (
    echo ERROR: The application failed to start with exit code %APP_EXIT_CODE%. >> setup_log.txt
    echo The application failed to start with exit code %APP_EXIT_CODE%.
) else (
    echo The application has exited.
)
echo Check setup_log.txt for any errors.
echo.
echo Press any key to exit...
pause > nul
