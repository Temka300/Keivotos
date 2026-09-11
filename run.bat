@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Keivotos - Danbooru

where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv is required to run Keivotos from source.
    echo [ERROR] Install it from https://docs.astral.sh/uv/
    pause
    exit /b 1
)

uv run --locked --python 3.11 run.py %*
set "KEIVOTOS_EXIT_CODE=%ERRORLEVEL%"
if not "%KEIVOTOS_EXIT_CODE%"=="0" (
    echo [ERROR] Keivotos setup or startup failed. See the output above.
    pause
)
exit /b %KEIVOTOS_EXIT_CODE%
