@echo off
title Mi casa
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0casa.ps1"
if errorlevel 1 pause
