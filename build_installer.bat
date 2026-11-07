@echo off
setlocal
cd /d "%~dp0"
title Build Jarvis-Setup.exe
echo.
echo ==============================================================
echo    Building the Jarvis Windows installer  (Jarvis-Setup.exe)
echo    This takes about 10-15 minutes. Please wait.
echo.
echo    NOTE: you do NOT type your Groq API key in this window.
echo    The key screen is part of Jarvis-Setup.exe itself - it is the
echo    2nd screen of the installer that this script builds.
echo ==============================================================
echo.

rem ---- find Python 3.10+ ----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY goto :nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 goto :nopython

rem ---- private environment + dependencies ----
if not exist "venv\Scripts\python.exe" (
    echo [1/6] Creating a private Python environment...
    %PY% -m venv venv
    if errorlevel 1 goto :fail
) else (
    echo [1/6] Python environment already exists - reusing it.
)
echo [2/6] Installing Jarvis components and PyInstaller...
"venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul
"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
"venv\Scripts\python.exe" -m pip install --upgrade pyinstaller
if errorlevel 1 goto :fail

rem ---- models + runtime that get bundled ----
echo [3/6] Fetching the wake-word model, hand-tracking model and Windows runtime...
"venv\Scripts\python.exe" prepare_build.py
if errorlevel 1 goto :fail

rem ---- build the program ----
echo [4/6] Bundling Jarvis into a Windows program (the slow step)...
"venv\Scripts\python.exe" -m PyInstaller jarvis.spec --noconfirm --clean
if errorlevel 1 goto :fail
if not exist "dist\Jarvis\Jarvis.exe" goto :fail

rem ---- self-test the packaged program ----
echo.
echo [5/6] Self-test of the packaged program (about 30 seconds)...
if exist "%LOCALAPPDATA%\Jarvis\selftest.txt" del "%LOCALAPPDATA%\Jarvis\selftest.txt" >nul 2>nul
start "" /wait "dist\Jarvis\Jarvis.exe" --selftest
set "ST=%errorlevel%"
echo.
if not exist "%LOCALAPPDATA%\Jarvis\selftest.txt" goto :noreport
type "%LOCALAPPDATA%\Jarvis\selftest.txt"
goto :reportdone
:noreport
echo No self-test report was written - the program may have failed to start at all.
set "ST=1"
:reportdone
if "%ST%"=="0" goto :buildsetup
echo.
echo ==============================================================
echo  SELF-TEST FAILED. Lines marked FAIL above mean Jarvis would
echo  not run properly on a customer's PC.
echo  Copy the text above and send it to whoever is helping you.
echo ==============================================================
choice /c YN /m "Build the installer anyway"
if errorlevel 2 goto :hold

:buildsetup
rem ---- build the installer with Inno Setup (installs it first if missing) ----
echo.
echo [6/6] Building the installer...
call :findinno
if defined ISCC goto :haveinno
echo Inno Setup - the free tool that makes Setup.exe - was not found on this PC.
choice /c YN /m "Install it now with winget (free)"
if errorlevel 2 goto :noinno
winget install -e --id JRSoftware.InnoSetup --accept-package-agreements --accept-source-agreements --silent
call :findinno
if not defined ISCC goto :noinno
:haveinno
"%ISCC%" jarvis_installer.iss
if errorlevel 1 goto :fail

echo.
echo ==============================================================
echo  DONE.  Your installer is here:
echo      %~dp0release\Jarvis-Setup.exe
echo.
echo  NEXT: test it yourself - double-click Jarvis-Setup.exe.
echo  Its 2nd screen asks for the Groq API key. Then send that one
echo  file to your customer.
echo ==============================================================
echo.
choice /c YN /m "Open the installer now to test it"
if errorlevel 2 goto :hold
start "" "%~dp0release\Jarvis-Setup.exe"
goto :hold

:noinno
echo.
echo The Jarvis program was built (dist\Jarvis\Jarvis.exe) but Setup.exe could not be made
echo because Inno Setup is missing. Install it from https://jrsoftware.org/isdl.php
echo and run build_installer.bat again.
goto :hold

:nopython
echo Python 3.10 or newer was not found. Install it from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH"), then run build_installer.bat again.
goto :hold

:fail
echo.
echo The build stopped because of an error - scroll up to read the message.
goto :hold

:hold
echo.
echo --------------------------------------------------------------
echo  This window stays open so you can read everything above.
echo  Type EXIT or click the X to close it.
echo  (Do not paste your API key here - Jarvis-Setup.exe asks for it.)
echo --------------------------------------------------------------
cmd /k
exit /b 0

:findinno
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
exit /b 0
