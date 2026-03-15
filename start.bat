@echo off
echo Starting Nutrition Feedback App...
echo.

cd /d "C:\Users\Mihaela\Desktop\vibecode\nutrition-feedback"

echo [1/2] Starting backend (port 3001)...
start "Backend" cmd /k "python -m uvicorn main:app --reload --host 0.0.0.0 --port 3001"

timeout /t 3 /nobreak >nul

echo [2/2] Starting frontend (port 8080)...
start "Frontend" cmd /k "python -m http.server 8080"

timeout /t 2 /nobreak >nul

echo Opening browser...
start chrome "http://localhost:8080"

echo.
echo Done! Your app is running.
echo Just close the two black windows when you want to stop.
pause
