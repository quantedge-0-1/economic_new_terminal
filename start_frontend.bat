@echo off
title Economic Terminal — Frontend (port 3000)
cd /d "%~dp0frontend"
echo Starting Economic News Terminal Frontend...
echo Terminal UI: http://localhost:3000
echo.
npm run dev
pause
