@echo off
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3.11 -V >nul 2>nul
  if not errorlevel 1 (
    py -3.11 install.py %*
    if errorlevel 1 exit /b 1
    exit /b 0
  )
  py -3.12 -V >nul 2>nul
  if not errorlevel 1 (
    py -3.12 install.py %*
    if errorlevel 1 exit /b 1
    exit /b 0
  )
  py -3.13 -V >nul 2>nul
  if not errorlevel 1 (
    py -3.13 install.py %*
    if errorlevel 1 exit /b 1
    exit /b 0
  )
  py -3.10 -V >nul 2>nul
  if not errorlevel 1 (
    py -3.10 install.py %*
    if errorlevel 1 exit /b 1
    exit /b 0
  )
)
echo Khong tim thay Python phu hop bang py launcher, thu python trong PATH.
python install.py %*
