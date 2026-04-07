@echo off
echo ============================================
echo  KVM RustDesk Switcher - Windows Installer
echo ============================================
echo.

:: Check admin
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: Please run this script as Administrator.
    echo Right-click and select "Run as administrator"
    pause
    exit /b 1
)

:: Get the directory this script is in
set "SCRIPT_DIR=%~dp0"

:: Read port from config
for /f "tokens=2 delims=:" %%a in ('findstr "listen_port" "%SCRIPT_DIR%kvm-config.json"') do (
    set "PORT=%%a"
)
set PORT=%PORT: =%
set PORT=%PORT:,=%

echo [1/2] Adding firewall rule for UDP port %PORT%...
netsh advfirewall firewall delete rule name="KVM RustDesk Switcher" >nul 2>&1
netsh advfirewall firewall add rule name="KVM RustDesk Switcher" dir=in action=allow protocol=UDP localport=%PORT% >nul
if %errorLevel% equ 0 (
    echo       Firewall rule added successfully.
) else (
    echo       WARNING: Failed to add firewall rule.
)

echo.
echo [2/2] Installing startup shortcut...
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
copy /y "%SCRIPT_DIR%start_kvm_listener.vbs" "%STARTUP%\start_kvm_listener.vbs" >nul
if %errorLevel% equ 0 (
    echo       Startup shortcut installed to: %STARTUP%
) else (
    echo       WARNING: Failed to copy startup shortcut.
)

echo.
echo ============================================
echo  Installation complete!
echo.
echo  To test now, run:
echo    python "%SCRIPT_DIR%kvm_listener.py"
echo.
echo  The listener will auto-start on next login.
echo ============================================
pause
