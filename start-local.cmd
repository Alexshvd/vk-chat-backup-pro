@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" "%~dp0run-local.py"
pause
