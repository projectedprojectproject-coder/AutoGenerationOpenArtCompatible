@echo off
cd /d "%~dp0"
powershell -NoProfile -Command "$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User'); uv run tools\shorts_cli.py install"
pause
