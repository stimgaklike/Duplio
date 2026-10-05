@echo off
chcp 65001 >nul
rem Сборка Duplio: программа в dist\Duplio и установщик dist\Duplio-Setup-<версия>.exe.
rem Нужны Python, python -m pip install pyinstaller pyside6, и Inno Setup 6.
cd /d "%~dp0"
for /f %%v in ('python -c "from version import VERSION; print(VERSION)"') do set VER=%%v
python -m PyInstaller --noconfirm --clean --onedir --windowed --name Duplio --icon icon.ico --add-data "icon.ico;." --add-data "icons;icons" --exclude-module tkinter --exclude-module PIL --exclude-module sv_ttk --exclude-module numpy --exclude-module yaml --exclude-module charset_normalizer --exclude-module setuptools --exclude-module pkg_resources app.py || exit /b 1
python prune_build.py
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
"%ISCC%" /Q /DAppVersion=%VER% installer.iss || exit /b 1
echo.
echo Готово: dist\Duplio\Duplio.exe и dist\Duplio-Setup-%VER%.exe
