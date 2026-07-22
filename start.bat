@echo off
cd /d e:\jobhunting\local-runner\local-runner

REM Save the current branch name
FOR /F "tokens=*" %%g IN ('git branch --show-current') do (SET CURRENT_BRANCH=%%g)

REM Switch to main branch
git checkout main

REM Run the server
python run.py

REM Switch back to original branch when the server is stopped
git checkout %CURRENT_BRANCH%
pause
