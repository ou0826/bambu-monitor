@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 打包（单文件 exe）===
echo 说明：单文件版第一次运行会解压到 %%TEMP%%，如果你机器上临时目录受限，
echo       可能报 "Could not create temporary directory"，那就用 build_exe.bat 的文件夹版。
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "拓竹打印监控-单文件" ^
  --icon "assets\app.ico" ^
  --add-data "assets;assets" ^
  --hidden-import paho.mqtt.client ^
  main.py
if errorlevel 1 goto :err
echo.
echo 完成: dist\拓竹打印监控-单文件.exe
pause
exit /b 0
:err
echo.
echo 失败，请查看上面的错误信息。
pause
exit /b 1
