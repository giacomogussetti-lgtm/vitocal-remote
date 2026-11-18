@echo off
title Vitocal 111-S & BTicino Remote Manager
echo ===================================================
echo  Avvio Gestionale Vitocal 111-S & BTicino Smarther
echo ===================================================
python "%~dp0app.py"
if %errorlevel% neq 0 (
    echo.
    echo Si e' verificato un errore durante l'avvio.
    pause
)
