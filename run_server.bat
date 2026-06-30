@echo off
REM SAP Test Studio -- local dashboard server launcher (Windows)
REM
REM Starts the FastAPI backend (studio\server.py) with hot reload.
REM studio\server.py loads .env itself (python-dotenv), so PORT/Azure/SAP
REM settings there are picked up automatically -- this script only needs to
REM pass --port through to uvicorn.
REM
REM Usage:
REM   run_server.bat            run on port 8501
REM   set PORT=9000 ^& run_server.bat   run on a custom port
REM ---------------------------------------------------------------------------
setlocal

if "%PORT%"=="" set PORT=8501

echo [run_server] Starting SAP Test Studio on http://localhost:%PORT% (reload enabled)
cd /d "%~dp0studio"
REM --reload-dir twice: app code (studio\, the default cwd) AND src\, since the
REM engine/sap/model packages live outside studio\ and wouldn't be watched
REM otherwise -- editing engine.py would silently not trigger a reload.
python -m uvicorn server:app --host 0.0.0.0 --port %PORT% --reload --reload-dir . --reload-dir ..\src
