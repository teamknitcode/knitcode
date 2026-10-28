@echo off
cd /d "%~dp0.."
py git_validation\integrated_cli.py %*
pause
