@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1

echo 正在启动 WEEX 交易所跟单...
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_BIN=py -3"
    goto run_python
)

where python >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_BIN=python"
    goto run_python
)

where winget >nul 2>nul
if %errorlevel%==0 (
    echo 未检测到 Python，正在通过 winget 自动安装 Python...
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    echo.
    echo Python 安装完成，正在继续启动...
    where py >nul 2>nul
    if %errorlevel%==0 (
        set "PYTHON_BIN=py -3"
        goto run_python
    )
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PYTHON_BIN=python"
        goto run_python
    )
    echo Python 已安装但当前窗口暂时未识别，请关闭窗口后重新双击 WEEX交易所.bat
    pause
    exit /b 1
)

echo 未检测到 Python，也未检测到 winget。
echo 请先在 Microsoft Store 安装 App Installer，或手动安装 Python 3 后重新双击本文件。
echo.
pause
exit /b 1

:run_python
%PYTHON_BIN% -u WEEX交易所.py
echo.
echo 程序已退出，按任意键关闭窗口...
pause >nul
