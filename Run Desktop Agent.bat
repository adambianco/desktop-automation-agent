@echo off
REM Desktop Automation Agent - Launcher
REM Uses PowerShell to find Python and launch the app (bypasses Windows App Execution Aliases)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run Desktop Agent.ps1"
