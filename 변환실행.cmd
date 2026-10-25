@echo off
chcp 65001 >nul
setlocal
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0main.py" %*
) else (
  echo 먼저 설치.cmd를 실행하거나 Python 환경에서 requirements.txt를 설치하세요.
)
pause
