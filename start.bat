@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo  Chat Memory  -  长期记忆服务
echo ========================================
python selfcheck.py
if errorlevel 1 (
    echo.
    echo 自检失败，先修好再启动。上面写着缺什么。
    pause
    exit /b 1
)
echo.
echo 启动中... 按 Ctrl+C 停止
python memory_service.py serve --port 5299
pause
