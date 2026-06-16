@echo off
REM run_qmt_gateway.bat — 使用 venv_qmt (Python 3.11) 运行 QMT 网关相关脚本
REM 用法: run_qmt_gateway.bat scripts\check_qmt_status.py
REM        run_qmt_gateway.bat gateways\qmt_gateway.py

set SCRIPT_DIR=%~dp0
set VENV_PYTHON=%SCRIPT_DIR%venv_qmt\Scripts\python.exe

if not exist "%VENV_PYTHON%" (
    echo ❌ venv_qmt 不存在: %VENV_PYTHON%
    echo 请先创建 venv: py -3.11 -m venv venv_qmt
    exit /b 1
)

echo 使用 Python 3.11 venv: %VENV_PYTHON%
"%VENV_PYTHON%" %*
