; Инсталатор за Windows (Inno Setup 6): класически съветник „Напред >“, който пита за версия,
; теми, град, брой истории, час и печат, после инсталира Python (ако няма), пакетите и задачата
; в Task Scheduler. Компилира се от GitHub Actions (.github/workflows/windows.yml):
;   python installer/windows/make_topics.py
;   iscc installer/windows/setup.iss        → dist/Sutreshen-Vestnik-Setup.exe
; Тих режим (за проверка): Setup.exe /VERYSILENT /version=lite /topics=bg,world /city=Пловдив /time=06:30 /print=0

#define AppName "Сутрешен вестник"
#define AppVersion "1.0"

[Setup]
AppId={{8C1F6B2E-5A7D-4E3B-9F21-6D0C4B7A9E13}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Sarkis Demirdjian
AppPublisherURL=https://sako4018.github.io/newspaper/
DefaultDirName={localappdata}\{#AppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=Sutreshen-Vestnik-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=classic
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\icon.ico
SetupIconFile=icon.ico
SetupLogging=yes

[Languages]
Name: "bg"; MessagesFile: "compiler:Languages\Bulgarian.isl"

[Messages]
WelcomeLabel2=Този съветник ще инсталира „Сутрешен вестник“ на компютъра ти.%n%nВсяка сутрин програмата събира новини от БТА, Дневник, BBC, Guardian и още около 80 източника и ги подрежда в Word документ (.docx) на Desktop.%n%nТрябва ти интернет и около 1 ГБ свободно място. Ако няма Python, съветникът го инсталира сам.

[Files]
Source: "..\..\app\*"; DestDir: "{app}\app"; Excludes: "__pycache__"; Flags: ignoreversion recursesubdirs
Source: "..\..\claude\*"; DestDir: "{app}\claude"; Excludes: "__pycache__,logs,newspapers,latest.docx"; Flags: ignoreversion recursesubdirs
Source: "..\..\lite\*"; DestDir: "{app}\lite"; Excludes: "__pycache__,output,profile.yaml,profile.tmp"; Flags: ignoreversion recursesubdirs
Source: "install.ps1"; DestDir: "{app}\installer\windows"; Flags: ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion
; Копие на самия инсталатор: с него се поправя инсталацията, ако нещо се счупи
Source: "{srcexe}"; DestDir: "{app}"; DestName: "Setup.exe"; Flags: external ignoreversion; Check: NotFromAppDir

; Преките пътища от v1.0 (бяха направо в Start, без папка)
[InstallDelete]
Type: files; Name: "{userprograms}\{#AppName} – настройки.lnk"
Type: files; Name: "{userprograms}\{#AppName} – направи брой сега.lnk"

[Icons]
; „Сутрешен вестник“ отваря приложението с настройки в браузъра (app/server.py). То спира само,
; когато страницата се затвори (--quit-when-idle), защото на Windows няма терминал с Ctrl+C.
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\app\server.py"" --quit-when-idle"; WorkingDir: "{app}\app"; IconFilename: "{app}\icon.ico"; Comment: "Теми, версия, час и брой сега"
Name: "{userprograms}\{#AppName}\{#AppName}"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\app\server.py"" --quit-when-idle"; WorkingDir: "{app}\app"; IconFilename: "{app}\icon.ico"; Comment: "Теми, версия, час и брой сега"
Name: "{userprograms}\{#AppName}\Направи брой сега"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\claude\run.py"""; WorkingDir: "{app}\claude"; IconFilename: "{app}\icon.ico"
Name: "{userprograms}\{#AppName}\Поправи инсталацията"; Filename: "{app}\Setup.exe"
Name: "{userprograms}\{#AppName}\Деинсталирай"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\claude\run.py"""; WorkingDir: "{app}\claude"; Description: "Направи първия брой сега"; Flags: postinstall nowait skipifsilent; Check: InstallOk
Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\app\server.py"" --quit-when-idle"; WorkingDir: "{app}\app"; Description: "Отвори настройките"; Flags: postinstall nowait skipifsilent unchecked; Check: InstallOk

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -Command ""Unregister-ScheduledTask -TaskName 'Sutreshen Vestnik' -Confirm:$false"""; Flags: runhidden; RunOnceId: "RemoveTask"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
var
  VersionPage, TopicsPage: TInputOptionWizardPage;
  OptionsPage: TInputQueryWizardPage;
  PrintBox: TNewCheckBox;
  TopicIds: TStringList;
  InstallFailed: Boolean;
  FailMessage: String;

#include "topics.isi"

function ClaudeInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{%USERPROFILE}\.local\bin\claude.exe'))
    or FileExists(ExpandConstant('{userappdata}\npm\claude.cmd'));
end;

function NotFromAppDir: Boolean;
begin
  Result := CompareText(ExpandConstant('{srcexe}'), ExpandConstant('{app}\Setup.exe')) <> 0;
end;

function InstallOk: Boolean;
begin
  Result := not InstallFailed;
end;

function SelectedVersion: String;
begin
  if VersionPage.SelectedValueIndex = 1 then Result := 'claude' else Result := 'lite';
end;

function TopicsCsv: String;
var
  I: Integer;
begin
  Result := '';
  for I := 0 to TopicIds.Count - 1 do
    if TopicsPage.Values[I] then begin
      if Result <> '' then Result := Result + ',';
      Result := Result + TopicIds[I];
    end;
end;

function DefaultCount: Integer;
begin
  if SelectedVersion = 'claude' then Result := 17 else Result := 4;
end;

function CountValue: Integer;
begin
  Result := StrToIntDef(Trim(OptionsPage.Values[1]), DefaultCount);
end;

function CountValid: Boolean;
begin
  if SelectedVersion = 'claude' then
    Result := (CountValue >= 5) and (CountValue <= 25)
  else
    Result := (CountValue >= 1) and (CountValue <= 10);
end;

{ Часът като „ЧЧ:ММ“; празен низ, ако е невалиден. }
function TimeValue: String;
var
  S: String;
  P, H, M: Integer;
begin
  Result := '';
  S := Trim(OptionsPage.Values[2]);
  P := Pos(':', S);
  if (P < 2) or (Length(S) - P <> 2) then Exit;
  H := StrToIntDef(Copy(S, 1, P - 1), -1);
  M := StrToIntDef(Copy(S, P + 1, 2), -1);
  if (H < 0) or (H > 23) or (M < 0) or (M > 59) then Exit;
  Result := Format('%.2d:%.2d', [H, M]);
end;

procedure InitializeWizard;
var
  Note: TNewStaticText;
  Saved: String;
  I: Integer;
begin
  TopicIds := TStringList.Create;

  VersionPage := CreateInputOptionPage(wpWelcome, 'Версия', 'Избери как да се подбират новините.',
    'Версията може да се смени по-късно от „Сутрешен вестник – настройки“.', True, False);
  VersionPage.Add('Lite: подбира по правила и превежда чуждите новини без интернет. Няколко страници.');
  VersionPage.Add('Claude: Claude обобщава и подрежда новините. Една страница A4.');
  Saved := GetPreviousData('Version', ExpandConstant('{param:version|lite}'));
  if Saved = 'claude' then VersionPage.SelectedValueIndex := 1 else VersionPage.SelectedValueIndex := 0;
  if not ClaudeInstalled then begin
    VersionPage.CheckListBox.Height := ScaleY(60);
    Note := TNewStaticText.Create(VersionPage);
    Note.Parent := VersionPage.Surface;
    Note.Top := VersionPage.CheckListBox.Top + VersionPage.CheckListBox.Height + ScaleY(12);
    Note.Width := VersionPage.SurfaceWidth;
    Note.WordWrap := True;
    Note.Caption := 'На този компютър няма Claude Code (командата claude). За версия Claude първо го инсталирай от claude.com/claude-code. Иначе избери Lite.';
  end;

  TopicsPage := CreateInputOptionPage(VersionPage.ID, 'Теми', 'Отметни темите, които искаш във вестника.',
    'Поне една тема.', False, False);
  AddTopics(TopicsPage);
  Saved := ',' + GetPreviousData('Topics', ExpandConstant('{param:topics|}')) + ',';
  for I := 0 to TopicIds.Count - 1 do
    TopicsPage.Values[I] := Pos(',' + TopicIds[I] + ',', Saved) > 0;

  OptionsPage := CreateInputQueryPage(TopicsPage.ID, 'Настройки', 'Град, брой истории, час и печат.', '');
  OptionsPage.Add('Град за времето (по желание, напр. Пловдив):', False);
  OptionsPage.Add('Брой истории (Lite: на тема, от 1 до 10; Claude: общо, от 5 до 25):', False);
  OptionsPage.Add('Всеки ден в (ЧЧ:ММ). Ако компютърът е изключен, вестникът се прави при включване:', False);
  OptionsPage.Values[0] := GetPreviousData('City', ExpandConstant('{param:city|}'));
  OptionsPage.Values[1] := GetPreviousData('Count', ExpandConstant('{param:count|}'));
  OptionsPage.Values[2] := GetPreviousData('Time', ExpandConstant('{param:time|06:00}'));
  PrintBox := TNewCheckBox.Create(OptionsPage);
  PrintBox.Parent := OptionsPage.Surface;
  PrintBox.Top := OptionsPage.Edits[2].Top + OptionsPage.Edits[2].Height + ScaleY(14);
  PrintBox.Width := OptionsPage.SurfaceWidth;
  PrintBox.Height := ScaleY(17);
  PrintBox.Caption := 'Печатай вестника на принтера всяка сутрин (когато имаш принтер)';
  PrintBox.Checked := GetPreviousData('Print', ExpandConstant('{param:print|0}')) = '1';
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = OptionsPage.ID) and (Trim(OptionsPage.Values[1]) = '') then
    OptionsPage.Values[1] := IntToStr(DefaultCount);
  if CurPageID = wpFinished then begin
    if InstallFailed then
      WizardForm.FinishedLabel.Caption := 'Инсталирането не завърши: ' + FailMessage + #13#10#13#10 +
        'Подробности има в ' + ExpandConstant('{app}\install.log') + '.' + #13#10 +
        'Пусни Start → „Сутрешен вестник“ → „Поправи инсталацията“, за да опиташ пак.'
    else
      WizardForm.FinishedLabel.Caption := 'Готово! Всеки ден в ' + TimeValue + ' вестникът се прави сам и се появява на Desktop.' + #13#10#13#10 +
        'Теми, версия и час сменяш от иконката „Сутрешен вестник“ на Desktop. Деинсталира се от Start → „Сутрешен вестник“ → „Деинсталирай“.';
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = TopicsPage.ID) and (TopicsCsv = '') then begin
    SuppressibleMsgBox('Избери поне една тема.', mbError, MB_OK, IDOK);
    Result := False;
  end;
  if CurPageID = OptionsPage.ID then begin
    if not CountValid then begin
      SuppressibleMsgBox('Броят истории е извън допустимото (Lite: 1-10, Claude: 5-25).', mbError, MB_OK, IDOK);
      Result := False;
    end else if TimeValue = '' then begin
      SuppressibleMsgBox('Часът трябва да е във вида ЧЧ:ММ, например 06:00.', mbError, MB_OK, IDOK);
      Result := False;
    end;
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  Names, City, Print: String;
  I: Integer;
begin
  Names := '';
  for I := 0 to TopicIds.Count - 1 do
    if TopicsPage.Values[I] then begin
      if Names <> '' then Names := Names + ', ';
      Names := Names + Copy(TopicsPage.CheckListBox.ItemCaption[I], 1, Pos(' (', TopicsPage.CheckListBox.ItemCaption[I] + ' (') - 1);
    end;
  City := Trim(OptionsPage.Values[0]);
  if City = '' then City := 'без град';
  if PrintBox.Checked then Print := 'да' else Print := 'не';
  Result := 'Версия:' + NewLine + Space + SelectedVersion + ', ' + IntToStr(CountValue) + ' истории' + NewLine + NewLine +
    'Теми:' + NewLine + Space + Names + NewLine + NewLine +
    'Град:' + NewLine + Space + City + NewLine + NewLine +
    'Всеки ден в:' + NewLine + Space + TimeValue + NewLine + NewLine +
    'Печат:' + NewLine + Space + Print + NewLine + NewLine +
    'Папка:' + NewLine + Space + ExpandConstant('{app}');
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
var
  Print: String;
begin
  if PrintBox.Checked then Print := '1' else Print := '0';
  SetPreviousData(PreviousDataKey, 'Version', SelectedVersion);
  SetPreviousData(PreviousDataKey, 'Topics', TopicsCsv);
  SetPreviousData(PreviousDataKey, 'City', Trim(OptionsPage.Values[0]));
  SetPreviousData(PreviousDataKey, 'Count', IntToStr(CountValue));
  SetPreviousData(PreviousDataKey, 'Time', TimeValue);
  SetPreviousData(PreviousDataKey, 'Print', Print);
end;

function JsonText(S: String): String;
begin
  StringChangeEx(S, '\', '\\', True);
  StringChangeEx(S, '"', '\"', True);
  Result := '"' + S + '"';
end;

{ settings.json за app\apply_settings.py }
procedure WriteSettings;
var
  Json, Topics: String;
  Lines: TArrayOfString;
  I: Integer;
begin
  Topics := '';
  for I := 0 to TopicIds.Count - 1 do
    if TopicsPage.Values[I] then begin
      if Topics <> '' then Topics := Topics + ', ';
      Topics := Topics + JsonText(TopicIds[I]);
    end;
  Json := '{"version": ' + JsonText(SelectedVersion) + ', "topics": [' + Topics + '], ';
  if SelectedVersion = 'claude' then
    Json := Json + '"max_stories": ' + IntToStr(CountValue) + ', '
  else
    Json := Json + '"stories_per_topic": ' + IntToStr(CountValue) + ', ';
  Json := Json + '"schedule_time": ' + JsonText(TimeValue) + ', ';
  if PrintBox.Checked then Json := Json + '"print": true, ' else Json := Json + '"print": false, ';
  if Trim(OptionsPage.Values[0]) <> '' then
    Json := Json + '"city_name": ' + JsonText(Trim(OptionsPage.Values[0])) + '}'
  else
    Json := Json + '"city": null}';
  SetArrayLength(Lines, 1);
  Lines[0] := Json;
  SaveStringsToUTF8File(ExpandConstant('{app}\settings.json'), Lines, False);
end;

{ Пуска една стъпка от install.ps1. При грешка запомня коя е. }
function RunStep(Step, Status: String): Boolean;
var
  Code: Integer;
begin
  WizardForm.StatusLabel.Caption := Status;
  WizardForm.FilenameLabel.Caption := '';
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\installer\windows\install.ps1') + '" -Step ' + Step,
    ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
  if not Result then begin
    InstallFailed := True;
    FailMessage := Status;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    WizardForm.ProgressGauge.Style := npbstMarquee;
    WriteSettings;
    if RunStep('python', 'Търся Python (ако няма, го инсталирам)...') then
      if RunStep('venv', 'Инсталирам пакетите (първия път отнема няколко минути)...') then
        if RunStep('settings', 'Записвам настройките...') then
          RunStep('schedule', 'Включвам ежедневното пускане...');
    WizardForm.ProgressGauge.Style := npbstNormal;
  end;
end;

{ В тих режим кодът на изход показва дали всичко е минало (за проверката в GitHub Actions). }
function GetCustomSetupExitCode: Integer;
begin
  if InstallFailed then Result := 1 else Result := 0;
end;

procedure DeinitializeSetup;
begin
  TopicIds.Free;
end;
