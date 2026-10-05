; Установщик Duplio (Inno Setup 6). Сборка: build.bat → ISCC /DAppVersion=1.2.3 installer.iss
; Ставится для текущего пользователя (без прав администратора) в %LOCALAPPDATA%\Programs\Duplio —
; поэтому обновление из программы проходит тихо, без запроса UAC.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6C7D2B1E-4E0B-4D51-9C0E-7B3A9D5E2F41}
AppName=Duplio
AppVersion={#AppVersion}
AppVerName=Duplio {#AppVersion}
AppPublisher=stimgaklike
AppPublisherURL=https://github.com/stimgaklike/Duplio
AppSupportURL=https://github.com/stimgaklike/Duplio/issues
AppUpdatesURL=https://github.com/stimgaklike/Duplio/releases
DefaultDirName={autopf}\Duplio
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=Duplio-Setup-{#AppVersion}
SetupIconFile=icon.ico
WizardSmallImageFile=branding\wizard-small-1x.bmp,branding\wizard-small-2x.bmp
WizardImageFile=branding\wizard-large-1x.bmp,branding\wizard-large-2x.bmp
UninstallDisplayIcon={app}\Duplio.exe
UninstallDisplayName=Duplio
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
VersionInfoVersion={#AppVersion}

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Старые файлы прошлой версии — чтобы не смешались с новыми.
Type: filesandordirs; Name: "{app}\_internal"
; Ранние пробные установки (до установщика) лежали в папках versions\<дата>.
Type: filesandordirs; Name: "{app}\versions"

[Files]
Source: "dist\Duplio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Duplio"; Filename: "{app}\Duplio.exe"
Name: "{autodesktop}\Duplio"; Filename: "{app}\Duplio.exe"; Tasks: desktopicon

[Run]
; После обычной установки — галочка «Запустить Duplio»; после тихого обновления из программы — запуск сразу.
Filename: "{app}\Duplio.exe"; Description: "{cm:LaunchProgram,Duplio}"; Flags: nowait postinstall

[UninstallDelete]
; Настройки и журнал — чтобы после удаления ничего не осталось.
Type: filesandordirs; Name: "{userappdata}\Duplio"
Type: filesandordirs; Name: "{localappdata}\Duplio"

[Code]
const
  AppMutex = 'DuplioAppMutex';

// Обновление из программы: она закрывается сразу после запуска установщика. Ждём до 30 секунд,
// пока она завершится; если открыта и после этого — просим закрыть (кроме тихого режима).
function InitializeSetup(): Boolean;
var
  i: Integer;
begin
  i := 0;
  while CheckForMutexes(AppMutex) and (i < 150) do
  begin
    Sleep(200);
    i := i + 1;
  end;
  Result := True;
  while CheckForMutexes(AppMutex) do
  begin
    if WizardSilent() then
    begin
      Result := False;
      Exit;
    end;
    if MsgBox(ExpandConstant('{cm:CloseDuplio}'), mbError, MB_RETRYCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  while CheckForMutexes(AppMutex) do
    if MsgBox(ExpandConstant('{cm:CloseDuplio}'), mbError, MB_RETRYCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
end;

[CustomMessages]
ru.CloseDuplio=Duplio сейчас открыт. Закрой программу (в трее у часов: правая кнопка → «Выход») и нажми «Повтор».
en.CloseDuplio=Duplio is running. Close it (tray icon next to the clock: right-click → “Exit”) and press “Retry”.
