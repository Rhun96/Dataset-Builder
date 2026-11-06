@echo off
cd /d "%~dp0"
echo [1/3] tests...
py -3 -m pytest -q
if errorlevel 1 (
  echo TESTS FAILED - send me the output above.
  pause
  exit /b 1
)
echo [2/3] demo data...
if not exist demo_data mkdir demo_data
py -3 tools\make_demo.py
echo [3/3] inspect...
py -3 tools\inspect_pool.py demo_data --target 500
echo DONE. If tables above - Stage 1 works for you too.
pause
