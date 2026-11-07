@echo off
rem Starts the Jarvis window WITH a console, so you can see error messages if it won't start.
rem (Normal use: just double-click the Jarvis desktop shortcut instead.)
cd /d "%~dp0"
call venv\Scripts\activate.bat
python app.py
echo.
pause
