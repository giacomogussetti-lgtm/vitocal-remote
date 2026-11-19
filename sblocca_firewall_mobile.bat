@echo off
chcp 65001 > nul
title Sblocco Firewall Windows - Porta 8080

echo ======================================================================
echo    SBLOCCO PORTA 8080 NEL FIREWALL DI WINDOWS PER VITOCAL REMOTE
echo ======================================================================
echo.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRORE] Questo script richiede i permessi di Amministratore.
    echo.
    echo Per applicarlo:
    echo 1. Fai clic destro su questo file: sblocca_firewall_mobile.bat
    echo 2. Clicca su "Esegui come amministratore"
    echo.
    pause
    exit /b 1
)

netsh advfirewall firewall add rule name="Vitocal Web Server (Porta 8080)" dir=in action=allow protocol=TCP localport=8080 profile=private,public

echo.
echo [SUCCESSO] Regola creata con successo! La porta 8080 e' ora aperta.
echo Ora lo smartphone connesso alla Wi-Fi puo' raggiungere: http://192.168.1.66:8080
echo.
pause
