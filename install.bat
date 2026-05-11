@echo off
REM Desktop Automation Agent - Installer
REM Launches the PowerShell installer (works on all Windows 10/11)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
