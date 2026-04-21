@echo off
setlocal

:: md-doc-pipeline setup script for Windows
:: Run once after cloning: init.bat

echo === md-doc-pipeline setup ===
echo.

:: Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo Error: Python is required but not found.
    echo Install Python 3.11+ from https://www.python.org/downloads/
    exit /b 1
)

for /f "tokens=*" %%i in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set PYTHON_VERSION=%%i
for /f "tokens=*" %%i in ('python -c "import sys; print(sys.version_info.minor)"') do set PYTHON_MINOR=%%i

if %PYTHON_MINOR% LSS 11 (
    echo Error: Python 3.11+ is required (found %PYTHON_VERSION%)
    exit /b 1
)
echo Python %PYTHON_VERSION%

:: Check uv
where uv >nul 2>&1
if errorlevel 1 (
    echo.
    echo uv not found. Installing uv...
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    echo uv installed. You may need to restart your terminal.
    echo Then re-run init.bat
    exit /b 1
)
for /f "tokens=*" %%i in ('uv --version') do echo uv %%i

:: Create virtual environment
echo.
echo Creating virtual environment...
uv venv
echo Virtual environment created at .venv\

:: Install dependencies
echo.
echo Installing dependencies...
uv sync --group dev
echo Dependencies installed.

:: Verify
echo.
echo Verifying installation...
uv run md-doc --help >nul 2>&1 && (echo md-doc CLI is working.) || (echo Warning: md-doc CLI failed to start.)

echo.
echo === Setup complete ===
echo.
echo To get started:
echo   .venv\Scripts\activate
echo   md-doc theme init workspace\acme\
echo   md-doc new doc proposal --in workspace\acme\
echo   md-doc build workspace\acme\

endlocal
