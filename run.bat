@echo off
setlocal
cd /d "%~dp0"

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw run.py
    exit /b 0
)

where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw run.py
    exit /b 0
)

where python >nul 2>nul
if %errorlevel%==0 (
    python run.py
    exit /b 0
)

echo No se encontro Python. Instala Python 3 desde https://python.org
pause
