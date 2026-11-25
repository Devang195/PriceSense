@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed or missing from PATH.
  pause
  exit /b 1
)
echo Starting PriceSense at http://127.0.0.1:8000
start "" /min cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8000"
python -m uvicorn pricesense_api_scraper.api:app --host 127.0.0.1 --port 8000
if errorlevel 1 (
  echo.
  echo Install dependencies using: python -m pip install -r requirements.txt
  pause
)
