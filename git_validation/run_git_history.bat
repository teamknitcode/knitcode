@echo off
cd /d "%~dp0.."
py git_validation\git_insights_cli.py %*
pause
