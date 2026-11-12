@echo off
setlocal
set "MCOSU_PYTHON="
if exist "%~dp0preview-python.txt" set /p "MCOSU_PYTHON=" < "%~dp0preview-python.txt"
if not defined MCOSU_PYTHON goto missing
if not exist "%MCOSU_PYTHON%" goto missing
"%MCOSU_PYTHON%" "%~dp0preview-runtime.py" launch --runtime "%~dp0." %*
set "result=%errorlevel%"
if not "%result%"=="0" if "%~1"=="" pause
exit /b %result%
:missing
echo Set preview-python.txt to the absolute path of your Python executable. 1>&2
if "%~1"=="" pause
exit /b 1
