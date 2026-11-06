@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m ui.app > run_app.log 2>&1
) else (
  python -m ui.app > run_app.log 2>&1
)
echo Exit code: %errorlevel%
type run_app.log
pause
