@echo off
echo Starting Trakt2EmbySync...

:: Start the Streamlit web interface
start cmd /k "echo Starting Streamlit web interface... & call .venv\Scripts\activate.bat & streamlit run app.py"

:: Wait a moment to allow the web interface to start
timeout /t 3 > nul

:: Start the console runner for continuous background sync
start cmd /k "echo Starting background sync scheduler... & cd "%~dp0" & .venv\Scripts\activate.bat & python console_runner.py --mode scheduler"

echo Application started! You can now:
echo - Configure settings in the web browser
echo - Monitor sync progress in the web browser
echo - Background sync will continue running even if you close the browser
echo.
echo Close both command windows to fully exit the application.
