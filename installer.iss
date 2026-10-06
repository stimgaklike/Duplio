; Установщик Duplio (Inno Setup 6). Сборка: build.bat → ISCC /DAppVersion=1.2.3 installer.iss
; Ставится для текущего пользователя (без прав администратора) в %LOCALAPPDATA%\Programs\Duplio —
; поэтому обновление из программы проходит тихо, без запроса UAC.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define UninstKey "{6C7D2B1E-4E0B-4D51-9C0E-7B3A9D5E2F41}_is1"

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
; Язык не спрашиваем, если язык Windows есть среди наших; при обновлении — прежний язык установки.
ShowLanguageDialog=auto
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
  GENERIC_WRITE = $40000000;
  OPEN_EXISTING = 3;

function CreateFileW(lpFileName: String; dwDesiredAccess, dwShareMode, lpSecurityAttributes,
  dwCreationDisposition, dwFlagsAndAttributes, hTemplateFile: Cardinal): THandle;
  external 'CreateFileW@kernel32.dll stdcall';
function WriteFile(hFile: THandle; const lpBuffer: AnsiString; nNumberOfBytesToWrite: Cardinal;
  var lpNumberOfBytesWritten: Cardinal; lpOverlapped: Cardinal): Boolean;
  external 'WriteFile@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

// Попросить открытый Duplio закрыться: тот же канал, по которому второй запуск передаёт ему папку
// (app.py: QUIT_REQUEST). Программа закрывается как от «Выход» из трея — если идёт поиск или сжатие,
// она сама спросит, и можно отказаться.
procedure AskDuplioToQuit();
var
  h: THandle;
  written: Cardinal;
  msg: AnsiString;
begin
  h := CreateFileW('\.\pipe\Duplio-' + GetUserNameString(), GENERIC_WRITE, 0, 0, OPEN_EXISTING, 0, 0);
  if h <> THandle(-1) then
  begin
    msg := 'duplio:quit';
    WriteFile(h, msg, Length(msg), written, 0);
    CloseHandle(h);
  end;
end;

// Duplio уже установлен — значит, это обновление: так и пишем в окне (см. InitializeWizard).
function IsUpdate(): Boolean;
begin
  Result := RegKeyExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#UninstKey}');
end;

function InstalledVersion(): String;
begin
  if not RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#UninstKey}',
                             'DisplayVersion', Result) then
    Result := '';
end;

function CloseQuestion(): String;
begin
  if IsUpdate() then
    Result := CustomMessage('CloseDuplioUpdate')
  else
    Result := CustomMessage('CloseDuplio');
end;

function DuplioClosedWithin(Seconds: Integer): Boolean;
var
  i: Integer;
begin
  i := 0;
  while CheckForMutexes(AppMutex) and (i < Seconds * 5) do
  begin
    Sleep(200);
    i := i + 1;
  end;
  Result := not CheckForMutexes(AppMutex);
end;

// Обновление из программы (/UPDATE=1, тихо): она закрывается сама сразу после запуска установщика —
// ждём до 30 секунд. Ручной запуск при открытой программе — сразу спрашиваем «закрыть?» и по «Да»
// закрываем её сами (раньше 30 секунд ничего не происходило, а потом просили закрыть вручную).
function InitializeSetup(): Boolean;
var
  asked: Boolean;
begin
  Result := True;
  asked := False;
  if WizardSilent() or (ExpandConstant('{param:UPDATE|0}') = '1') then
    DuplioClosedWithin(30);
  while CheckForMutexes(AppMutex) do
  begin
    if WizardSilent() then
    begin
      Result := False;
      Exit;
    end;
    // Не закрылся сам — версии до 1.1.0 не понимают просьбу установщика, или программа ждёт ответа
    // в своём окне («идёт сжатие…»): тогда объясняем, как закрыть её вручную.
    if asked then
    begin
      if MsgBox(CustomMessage('CloseDuplioManual'), mbError, MB_RETRYCANCEL) = IDCANCEL then
      begin
        Result := False;
        Exit;
      end;
      DuplioClosedWithin(1);
    end
    else
    begin
      if MsgBox(CloseQuestion(), mbConfirmation, MB_YESNO) = IDNO then
      begin
        Result := False;
        Exit;
      end;
      asked := True;
      AskDuplioToQuit();
      DuplioClosedWithin(10);
    end;
  end;
end;

procedure InitializeWizard();
begin
  if IsUpdate() then
    WizardForm.Caption := FmtMessage(CustomMessage('UpdateCaption'), ['{#AppVersion}']);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if not IsUpdate() then
    Exit;
  if CurPageID = wpReady then
  begin
    WizardForm.PageNameLabel.Caption := CustomMessage('UpdateReadyTitle');
    WizardForm.PageDescriptionLabel.Caption := FmtMessage(CustomMessage('UpdateReadyText'), [InstalledVersion(), '{#AppVersion}']);
    WizardForm.NextButton.Caption := CustomMessage('UpdateButton');
  end
  else if CurPageID = wpInstalling then
  begin
    WizardForm.PageNameLabel.Caption := CustomMessage('UpdatingTitle');
    WizardForm.PageDescriptionLabel.Caption := CustomMessage('UpdatingText');
  end
  else if CurPageID = wpFinished then
  begin
    WizardForm.FinishedHeadingLabel.Caption := CustomMessage('UpdateDoneTitle');
    WizardForm.FinishedLabel.Caption := FmtMessage(CustomMessage('UpdateDoneText'), ['{#AppVersion}']);
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  while CheckForMutexes(AppMutex) do
  begin
    if MsgBox(CustomMessage('CloseDuplioUninstall'), mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := False;
      Exit;
    end;
    AskDuplioToQuit();
    DuplioClosedWithin(15);
  end;
end;

[CustomMessages]
ru.CloseDuplio=Duplio сейчас открыт. Закрыть его и продолжить установку?
ru.CloseDuplioUpdate=Duplio сейчас открыт. Закрыть его и продолжить обновление?
ru.CloseDuplioManual=Duplio не закрылся сам: старые версии этого не умеют, или он ждёт ответа в своём окне. Закрой его (значок у часов → правая кнопка → «Выход») и нажми «Повтор».
ru.CloseDuplioUninstall=Duplio сейчас открыт. Закрыть его и продолжить удаление?
ru.UpdateCaption=Обновление Duplio до версии %1
ru.UpdateReadyTitle=Всё готово к обновлению
ru.UpdateReadyText=Duplio %1 будет обновлён до версии %2. Настройки сохранятся.
ru.UpdateButton=&Обновить
ru.UpdatingTitle=Обновление
ru.UpdatingText=Подождите, Duplio обновляется.
ru.UpdateDoneTitle=Duplio обновлён
ru.UpdateDoneText=Установлена версия %1.
en.CloseDuplio=Duplio is running. Close it and continue the installation?
en.CloseDuplioUpdate=Duplio is running. Close it and continue the update?
en.CloseDuplioManual=Duplio did not close by itself: older versions can't, or it is waiting for an answer in its window. Close it (tray icon next to the clock → right-click → “Exit”) and press “Retry”.
en.CloseDuplioUninstall=Duplio is running. Close it and continue the uninstall?
en.UpdateCaption=Updating Duplio to version %1
en.UpdateReadyTitle=Ready to update
en.UpdateReadyText=Duplio %1 will be updated to version %2. Your settings are kept.
en.UpdateButton=&Update
en.UpdatingTitle=Updating
en.UpdatingText=Please wait while Duplio is being updated.
en.UpdateDoneTitle=Duplio is updated
en.UpdateDoneText=Version %1 is installed.
