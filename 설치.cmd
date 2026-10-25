@echo off
chcp 65001 >nul
setlocal
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m venv "%~dp0.venv"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3.11 이상을 설치한 뒤 다시 실행하세요.
    pause
    exit /b 1
  )
  python -m venv "%~dp0.venv"
)
if errorlevel 1 exit /b 1
"%~dp0.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 exit /b 1
echo 설치가 완료되었습니다. 변환실행.cmd를 실행하세요.
pause
