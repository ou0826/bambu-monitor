@echo off
chcp 65001 >nul
rem ============================================================
rem  一键「先开监控，再开 Bambu Studio」
rem
rem  用途：如果你不想让监控开机自启常驻后台，
rem        把这个文件的快捷方式放到桌面，
rem        以后用这个图标启动 Bambu Studio 即可，
rem        监控会跟着一起起来。
rem
rem  用法：右键本文件 → 发送到 → 桌面快捷方式
rem        （图标以后可以改成 Bambu Studio 的图标）
rem ============================================================
setlocal enabledelayedexpansion

set "MONITOR=%~dp0拓竹打印监控.exe"
if not exist "%MONITOR%" (
    echo 找不到监控程序：%MONITOR%
    echo 请把本文件放在「拓竹打印监控.exe」同一个文件夹里。
    pause
    exit /b 1
)

rem ---------- 找 Bambu Studio ----------
set "STUDIO="
for %%P in (
    "%ProgramFiles%\Bambu Studio\bambu-studio.exe"
    "%ProgramFiles(x86)%\Bambu Studio\bambu-studio.exe"
    "%LOCALAPPDATA%\Programs\Bambu Studio\bambu-studio.exe"
    "%APPDATA%\BambuStudio\bambu-studio.exe"
) do (
    if exist %%P if not defined STUDIO set "STUDIO=%%~P"
)

rem 注册表兜底（卸载项里登记的 DisplayIcon）
if not defined STUDIO (
    for /f "tokens=2,*" %%a in ('reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s /v DisplayIcon 2^>nul ^| findstr /i "bambu-studio.exe"') do (
        if not defined STUDIO set "STUDIO=%%b"
    )
)
if defined STUDIO set "STUDIO=%STUDIO:"=%"

if not defined STUDIO (
    echo.
    echo 没有自动找到 Bambu Studio。
    echo 请用记事本打开本文件，把下面这行的路径改成你的实际安装位置：
    echo     set "STUDIO=你的\bambu-studio.exe 完整路径"
    echo.
    pause
    exit /b 1
)

rem ---------- 先起监控（已经在跑就直接开面板） ----------
start "" "%MONITOR%"
rem 给它 2 秒把连接建好，再开 Studio
timeout /t 2 /nobreak >nul
start "" "%STUDIO%"
exit /b 0
