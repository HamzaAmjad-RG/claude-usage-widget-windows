@echo off
REM Claude Usage Monitor Startup Script
REM This batch file starts the Claude usage monitoring application

cd /d "%~dp0"
python claude_usage_menubar.py
