@echo off
chcp 65001 > nul
title Vitocal Remote - App Mobile Server

echo ======================================================================
echo    AVVIO SERVER APP MOBILE (ANDROID / PWA) - VITOCAL REMOTE
echo ======================================================================
echo.

cd /d "%~dp0"

python web_server.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERRORE] Impossibile avviare il server web.
    pause
)
