@echo off
cd /d "%~dp0.."
py git_validation\change_review_cli.py %*
pause
