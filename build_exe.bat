@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pyinstaller.exe" (
  set "PYI=.venv\Scripts\pyinstaller.exe"
) else (
  where pyinstaller >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] PyInstaller не найден. Установите: .venv\Scripts\pip install pyinstaller
    pause
    exit /b 1
  )
  set "PYI=pyinstaller"
)

%PYI% --onedir --console --noconfirm --clean ^
  --name VkChatBackup ^
  --add-data "WebApp/templates;WebApp/templates" ^
  --paths WebApp --paths ExportMessageToMd --paths Config run.py
if errorlevel 1 (
  echo [ERROR] Сборка провалилась.
  pause
  exit /b 1
)

copy /Y config.json "dist\VkChatBackup\config.json" >nul

set "APP_DIR=%~dp0dist\VkChatBackup"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$s = $ws.CreateShortcut('%APP_DIR%\VkChatBackupWithArgs.lnk'); " ^
  "$s.TargetPath = '%APP_DIR%\VkChatBackup.exe'; " ^
  "$s.Arguments = '--mode web --port 5000 --config config.json'; " ^
  "$s.WorkingDirectory = '%APP_DIR%'; " ^
  "$s.IconLocation = '%APP_DIR%\VkChatBackup.exe, 0'; " ^
  "$s.Save()"
if errorlevel 1 (
  echo [WARN] Не удалось создать ярлык VkChatBackupWithArgs.lnk
) else (
  echo Создан ярлык: VkChatBackupWithArgs.lnk
)
set "APP_DIR="

echo.
echo Готово: dist\VkChatBackup\
echo   - VkChatBackup.exe
echo   - _internal\
echo   - config.json
echo   - VkChatBackupWithArgs.lnk
pause
