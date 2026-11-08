@echo off
rem ============================================================
rem  Launcher wrapper (ASCII only, on purpose).
rem  Real logic lives in launcher.ps1 next to this file.
rem
rem  Why ASCII: cmd.exe parses .bat files in the OEM codepage,
rem  so a UTF-8 .bat with Chinese text explodes into garbage
rem  commands. Keep this file 7-bit and let PowerShell print
rem  the Chinese messages.
rem ============================================================
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1"
if errorlevel 1 (
    echo.
    echo Exit code: %errorlevel%
    pause
)
endlocal
