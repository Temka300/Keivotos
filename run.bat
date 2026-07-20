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

echo [SETUP] Synchronizing the locked Python 3.11 environment...
uv sync --locked --python 3.11
if errorlevel 1 (
    echo [ERROR] Python dependency synchronization failed.
    pause
    exit /b 1
)

if not exist "frontend\dist\index.html" (
    where npm.cmd >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] The frontend is not built and Node.js is unavailable.
        echo [ERROR] Install current Node.js LTS, then run run.bat again.
        pause
        exit /b 1
    )
    echo [SETUP] Installing locked frontend dependencies...
    pushd frontend
    call npm.cmd ci
    if errorlevel 1 (
        popd
        echo [ERROR] Frontend dependency installation failed.
        pause
        exit /b 1
    )
    call npm.cmd run build
    if errorlevel 1 (
        popd
        echo [ERROR] Frontend build failed.
        pause
        exit /b 1
    )
    popd
)

echo [RUN] Starting Keivotos - Danbooru...
".venv\Scripts\python.exe" app.py %*

if errorlevel 1 (
    echo [ERROR] Keivotos exited with an error.
    pause
)
