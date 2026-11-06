@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m PyInstaller DatasetBuilder.spec --noconfirm
) else (
  python -m PyInstaller DatasetBuilder.spec --noconfirm
)
echo Exit code: %errorlevel%
echo Result: dist\DatasetBuilderV2\DatasetBuilderV2.exe
pause
