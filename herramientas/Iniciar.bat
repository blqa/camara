@echo off
title Mi casa
cd /d "%~dp0"
python casa.py
if errorlevel 1 pause
