@echo off
setlocal EnableExtensions
title Codex Assistant - build exe
cd /d "%~dp0"

echo.
echo ============================================
echo    Codex Assistant GUI  -  build standalone exe
echo ============================================
echo.
echo  Building needs a one-time real Python install.
echo  The final CodexGUI.exe needs NO Python to run.
echo.

set "SRC=%~dp0"

if exist "%SRC%resources\codex-relay.exe" goto have_res
echo [x] Missing resources\codex-relay.exe
echo     Keep all files in the CodexGUI-exe folder together.
goto end_fail

:have_res
set "BUILDDIR=%LOCALAPPDATA%\CodexGUI_exe_build"
if exist "%BUILDDIR%" rmdir /s /q "%BUILDDIR%"
mkdir "%BUILDDIR%\resources"
copy /y "%SRC%codex-gui.py" "%BUILDDIR%\" >nul
copy /y "%SRC%app.ico"      "%BUILDDIR%\" >nul
copy /y "%SRC%resources\codex-relay.exe"   "%BUILDDIR%\resources\" >nul
copy /y "%SRC%resources\relay-gateway.exe" "%BUILDDIR%\resources\" >nul
cd /d "%BUILDDIR%"

REM ---- find a real Python that has pip ----
set "PYLAUNCH="
where py >nul 2>nul
if errorlevel 1 goto try_python
py -3 -m pip --version >nul 2>nul
if errorlevel 1 goto try_python
set "PYLAUNCH=py -3"
goto have_py

:try_python
where python >nul 2>nul
if errorlevel 1 goto no_python
python -m pip --version >nul 2>nul
if errorlevel 1 goto python_no_pip
set "PYLAUNCH=python"
goto have_py

:no_python
echo [x] No Python found.
echo     Please install the official Python 3.11+ from:
echo        https://www.python.org/downloads/
echo     In the installer, check these two options:
echo        1. Add python.exe to PATH
echo        2. Install tcl/tk graphical support
echo     Then run this file again.
goto end_fail

:python_no_pip
echo [x] The 'python' on PATH has NO pip.
echo     It looks like a bundled venv python (e.g. from
echo     an agent app), not a real Python.
echo     Please install the official Python 3.11+ from:
echo        https://www.python.org/downloads/
echo     In the installer, check these two options:
echo        1. Add python.exe to PATH
echo        2. Install tcl/tk graphical support
echo     Then run this file again.
goto end_fail

:have_py
echo [1/3] Using launcher: %PYLAUNCH%
%PYLAUNCH% -c "import tkinter" >nul 2>nul
if errorlevel 1 goto no_tk
echo [2/3] Installing / upgrading PyInstaller ...
%PYLAUNCH% -m pip install --upgrade pip >nul 2>nul
%PYLAUNCH% -m pip install --upgrade pyinstaller
if errorlevel 1 goto pip_fail
echo [3/3] Building exe (takes 1-3 minutes, please wait) ...
%PYLAUNCH% -m PyInstaller --noconfirm --clean --onefile --windowed --name CodexGui --icon app.ico --add-data "resources;resources" codex-gui.py
if errorlevel 1 goto build_fail
if not exist "%BUILDDIR%\dist\CodexGui.exe" goto no_out
copy /y "%BUILDDIR%\dist\CodexGui.exe" "%SRC%CodexGUI.exe" >nul
echo.
echo ============================================
echo    SUCCESS !  Your app is here:
echo       %SRC%CodexGUI.exe
echo    Double-click CodexGUI.exe on Windows.
echo    It does NOT need Python or .NET installed.
echo ============================================
explorer.exe /select,"%SRC%CodexGUI.exe"
goto end_ok

:no_tk
echo [x] Your Python is missing tkinter (tcl/tk).
echo     Reinstall Python and enable "tcl/tk" support.
goto end_fail

:pip_fail
echo [x] Failed to install PyInstaller. Check your network.
goto end_fail

:build_fail
echo [x] PyInstaller build failed. See messages above.
goto end_fail

:no_out
echo [x] Build finished but dist\CodexGui.exe not found.
goto end_fail

:end_ok
pause
endlocal
exit /b 0

:end_fail
echo.
pause
endlocal
exit /b 1
