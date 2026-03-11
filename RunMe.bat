@echo off
cd /d "%~dp0"
cls

echo.
echo  ============================================================
echo   Hey JT! Gavin needs a small file from your computer so
echo   the R4V automation can post comments as Roll4Veterans.
echo   This takes about 2 minutes. Just read each step and hit
echo   Enter when you're ready.
echo  ============================================================
echo.
pause

cls
echo.
echo  ============================================================
echo   STEP 1 of 4 — Checking that Python is installed
echo  ============================================================
echo.
echo  Just checking your computer has what it needs. No action
echo  required from you — this happens automatically.
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  Python is not installed on this computer.
    echo.
    echo  Here is what to do:
    echo    1. Open a browser and go to: python.org/downloads
    echo    2. Click the big Download button
    echo    3. Run the installer — check "Add Python to PATH" at
    echo       the bottom before clicking Install
    echo    4. Once installed, double-click RunMe.bat again
    echo.
    pause
    exit /b 1
)

echo  Python is installed. Good to go.
echo.
pause

cls
echo.
echo  ============================================================
echo   STEP 2 of 4 — Installing required tools
echo  ============================================================
echo.
echo  This installs the Google software needed to talk to YouTube.
echo  It only installs it for you (not system-wide) and only
echo  needs to happen once. Takes about 30 seconds.
echo.
echo  You may see a bunch of text scroll by — that is normal.
echo.
pause

python -m pip install --quiet --user google-auth-oauthlib google-api-python-client
if errorlevel 1 (
    echo.
    echo  Something went wrong installing tools.
    echo  Take a screenshot and text it to Gavin.
    pause
    exit /b 1
)

echo.
echo  Tools installed successfully.
echo.
pause

cls
echo.
echo  ============================================================
echo   STEP 3 of 4 — Sign in to YouTube
echo  ============================================================
echo.
echo  Here is exactly what is about to happen:
echo.
echo    1. Your default web browser will open automatically to
echo       a Google sign-in page.
echo.
echo    2. Sign in with the Google account that owns the
echo       Roll4Veterans YouTube channel (your R4V account).
echo       If you see multiple accounts listed, pick that one.
echo.
echo    3. Google will show a warning that says the app is not
echo       verified. This is normal — it is Gavin's app and he
echo       has not published it publicly. Click "Continue" anyway.
echo.
echo    4. Google will ask if R4V YouTube Manager can access
echo       your YouTube account. Click "Allow".
echo.
echo    5. The browser will show a page that says:
echo       "The authentication flow has completed."
echo       That means it worked.
echo.
echo    6. Come back to THIS window and hit Enter.
echo.
echo  Ready? Hit Enter and your browser will open.
echo.
pause

python auth_jt.py
if errorlevel 1 (
    echo.
    echo  Something went wrong during sign-in.
    echo  Take a screenshot and text it to Gavin.
    pause
    exit /b 1
)

if not exist token_jt.json (
    echo.
    echo  Sign-in did not complete — the file was not created.
    echo  Take a screenshot and text it to Gavin.
    pause
    exit /b 1
)

echo.
echo  Sign-in worked.
echo.
pause

cls
echo.
echo  ============================================================
echo   STEP 4 of 4 — Send the file to Gavin
echo  ============================================================
echo.
echo  The sign-in created a small file that Gavin needs.
echo  It is being copied to your clipboard right now.
echo.
type token_jt.json | clip
echo.
echo  Done. The file contents are on your clipboard.
echo.
echo  Here is what to do next:
echo.
echo    1. Open WhatsApp on this computer (or your phone).
echo    2. Open your chat with Gavin.
echo    3. Click in the message box and press Ctrl+V to paste.
echo    4. Send the message.
echo.
echo  It will look like a big block of scrambled text —
echo  that is normal. Just send it as-is.
echo.
echo  ============================================================
echo   That is it! Thanks JT. You can close this window.
echo  ============================================================
echo.
pause
