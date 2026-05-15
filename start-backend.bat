@echo off
REM EasyEDA AI Copilot — Backend Startup Script (Windows)
REM Starts the local FastAPI server on port 5120

echo ================================================
echo   EasyEDA AI Copilot — Local Backend Server
echo ================================================
echo.
echo Installing dependencies...

cd /d "%~dp0backend"
pip install -r requirements.txt --quiet

echo.
echo Starting server on http://localhost:5120
echo Press Ctrl+C to stop
echo.

python -m uvicorn main:app --host 0.0.0.0 --port 5120 --reload

pause
