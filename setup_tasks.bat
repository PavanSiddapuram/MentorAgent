@echo off
REM MentorAgent — Windows Task Scheduler Setup
REM Creates 3 scheduled tasks: Morning (7 AM), Evening (9 PM), Weekly (Sunday 10 PM)
REM Run this script as Administrator

SET PYTHON_PATH=C:\Users\Sidda\AppData\Local\Python\Python311\python.exe
SET SCRIPT_PATH=c:\Users\Sidda\OneDrive\Desktop\Projects\Agents\MentorAgent\mentor_scheduler.py
SET WORK_DIR=c:\Users\Sidda\OneDrive\Desktop\Projects\Agents\MentorAgent

echo Creating MentorAgent scheduled tasks...

REM Morning Flow — 7:00 AM daily
schtasks /Create /TN "MentorAgent\Morning" /TR "\"%PYTHON_PATH%\" \"%SCRIPT_PATH%\" --test morning" /SC DAILY /ST 07:00 /F /RL HIGHEST
echo [OK] Morning task created (7:00 AM daily)

REM Evening Flow — 9:00 PM daily
schtasks /Create /TN "MentorAgent\Evening" /TR "\"%PYTHON_PATH%\" \"%SCRIPT_PATH%\" --test evening" /SC DAILY /ST 21:00 /F /RL HIGHEST
echo [OK] Evening task created (9:00 PM daily)

REM Weekly Summary — Sunday 10:00 PM
schtasks /Create /TN "MentorAgent\Weekly" /TR "\"%PYTHON_PATH%\" \"%SCRIPT_PATH%\" --test weekly" /SC WEEKLY /D SUN /ST 22:00 /F /RL HIGHEST
echo [OK] Weekly task created (Sunday 10:00 PM)

echo.
echo All tasks created! Verify with:
echo   schtasks /Query /TN "MentorAgent\Morning"
echo   schtasks /Query /TN "MentorAgent\Evening"
echo   schtasks /Query /TN "MentorAgent\Weekly"
echo.
echo To remove all tasks later:
echo   schtasks /Delete /TN "MentorAgent\Morning" /F
echo   schtasks /Delete /TN "MentorAgent\Evening" /F
echo   schtasks /Delete /TN "MentorAgent\Weekly" /F
pause
