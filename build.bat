@echo off
chcp 65001 >nul
rem Сборка Duplio: программа в dist\Duplio и установщик dist\Duplio-Setup-<версия>.exe.
rem Нужны Python, python -m pip install pyinstaller pyside6 pillow numpy, и Inno Setup 6.
rem Программы для сжатия (jpegtran, oxipng, ffmpeg) скачиваются в third_party\ с проверкой SHA-256.
cd /d "%~dp0"
for /f %%v in ('python -c "from version import VERSION; print(VERSION)"') do set VER=%%v
python tools\fetch_tools.py || exit /b 1
python -m PyInstaller --noconfirm --clean --onedir --windowed --name Duplio --icon icon.ico --add-data "icon.ico;." --add-data "icons;icons" --add-data "THIRD_PARTY_NOTICES.md;." --exclude-module tkinter --exclude-module sv_ttk --exclude-module yaml --exclude-module charset_normalizer --exclude-module setuptools --exclude-module pkg_resources app.py || exit /b 1
python prune_build.py
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
"%ISCC%" /Q /DAppVersion=%VER% installer.iss || exit /b 1
echo.
echo Готово: dist\Duplio\Duplio.exe и dist\Duplio-Setup-%VER%.exe
