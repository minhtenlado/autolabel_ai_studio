@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Hay chay setup.bat truoc.
 exit /b 1
)
".venv\Scripts\python.exe" launch.py
