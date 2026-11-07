@echo off
chcp 65001 >nul
rem ============================================================
rem  一键「先开监控，再开 Bambu Studio」
rem  用法：把这个 bat 的快捷方式放到桌面，替换原来 Bambu Studio 的快捷方式即可。
rem  如果你不想让监控常驻后台，这是最省事的方案。
rem ============================================================
setlocal

set "MONITOR=%~dp0..\dist\拓竹打印监控\拓竹打印监控.exe"
if not exist "%MONITOR%" set "MONITOR=%~dp0..\拓竹打印监控.exe"

rem Bambu Studio 路径：优先用注册表里登记的位置，找不到就用下面这个默认值
set "STUDIO=E:\3D Apps\Bambu Studio\bambu-studio.exe"
for /f "tokens=2,*" %%a in ('reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s /v DisplayIcon 2^>nul ^| findstr /i "bambu-studio.exe"') do (
    set "STUDIO=%%b"
)
set "STUDIO=%STUDIO:"=%"

if not exist "%MONITOR%" (
    echo 找不到监控程序: %MONITOR%
    pause
    exit /b 1
)
if not exist "%STUDIO%" (
    echo 找不到 Bambu Studio: %STUDIO%
    echo 请用记事本打开本文件，把 STUDIO 改成你的实际路径。
    pause
    exit /b 1
)

start "" "%MONITOR%" --minimized
rem 等 2 秒，让监控先把 MQTT 会话建好
timeout /t 2 /nobreak >nul
start "" "%STUDIO%"
