@echo off
title Economic Terminal — Backend (port 8001)
cd /d "%~dp0backend"
echo Starting Economic News Terminal Backend...
echo API Docs: http://127.0.0.1:8001/docs
echo.
python -m uvicorn app.main:app --reload --port 8001
pause
