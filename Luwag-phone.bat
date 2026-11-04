@echo off
cd /d "%~dp0"
pythonw app.py --phone
if errorlevel 1 python app.py --phone
