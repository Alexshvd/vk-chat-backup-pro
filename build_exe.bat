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

echo Очистка промежуточных файлов...
rmdir /s /q build 2>nul

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

echo.
echo Готово: dist\VkChatBackup\
echo   - VkChatBackup.exe
echo   - _internal\
echo   - config.json
pause
