@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 安装依赖 ===
python -m pip install -r requirements.txt
if errorlevel 1 goto :err

echo.
echo === 打包（文件夹版，推荐）===
echo 说明：文件夹版不需要解压到临时目录，最稳，启动也最快。
python -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name "拓竹打印监控" ^
  --icon "assets\app.ico" ^
  --add-data "assets;assets" ^
  --hidden-import paho.mqtt.client ^
  main.py
if errorlevel 1 goto :err

echo.
echo 完成: dist\拓竹打印监控\拓竹打印监控.exe
echo （整个 dist\拓竹打印监控 文件夹可以直接拷到别的电脑用）
pause
exit /b 0
:err
echo.
echo 失败，请查看上面的错误信息。
pause
exit /b 1
