; Inno Setup script - builds release\Jarvis-Setup.exe
; Needs Inno Setup 6.3 or newer (free): https://jrsoftware.org/isdl.php
; Edit the #define lines below, then run build_installer.bat (or compile this file in Inno Setup).

#define MyAppName "Jarvis Voice Assistant"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Your Company Name"

; If prepare_build.py managed to download Microsoft's Visual C++ runtime, it is bundled and
; installed automatically on PCs that lack it (clean Windows installs often do).
#if FileExists("redist\vc_redist.x64.exe")
  #define HaveVCRedist
#endif

[Setup]
AppId={{37C8B635-A48C-4B5B-BBF3-BE2D6F079020}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Jarvis
DefaultGroupName=Jarvis
DisableProgramGroupPage=yes
; Windows 10 (version 1809) or newer, 64-bit only: what the speech / hand-tracking libraries need.
MinVersion=10.0.17763
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Per-user install: no administrator prompt, and Jarvis can keep its files in the user's profile.
PrivilegesRequired=lowest
OutputDir=release
OutputBaseFilename=Jarvis-Setup
SetupIconFile=jarvis.ico
UninstallDisplayIcon={app}\Jarvis.exe
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Setup asks the customer to close Jarvis first if it is running (matches the mutex in app.py).
AppMutex=Local\JarvisVoiceAssistantSingleton

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nIn the next step you will enter your Groq API key. Jarvis uses it to understand and answer you. You can get a free key at console.groq.com/keys.%n%nClick Next to continue.

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start Jarvis automatically when Windows starts"; GroupDescription: "Options:"; Flags: unchecked

[Files]
Source: "dist\Jarvis\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "CUSTOMER_GUIDE.txt"; DestDir: "{app}"; Flags: ignoreversion
#ifdef HaveVCRedist
Source: "redist\vc_redist.x64.exe"; Flags: dontcopy
#endif

[Icons]
Name: "{autoprograms}\Jarvis"; Filename: "{app}\Jarvis.exe"; WorkingDir: "{app}"
Name: "{autoprograms}\Jarvis user guide"; Filename: "{app}\CUSTOMER_GUIDE.txt"
Name: "{autodesktop}\Jarvis"; Filename: "{app}\Jarvis.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\Jarvis"; Filename: "{app}\Jarvis.exe"; WorkingDir: "{app}"; Tasks: startup

[Run]
Filename: "{app}\Jarvis.exe"; Description: "Start Jarvis now"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Removes the saved API key, settings and logs when the customer uninstalls.
Type: filesandordirs; Name: "{localappdata}\Jarvis"

[Code]
var
  KeyPage: TInputQueryWizardPage;
  KeyLink: TNewStaticText;
  SavedKey: String;

function DataDir: String;
begin
  Result := ExpandConstant('{localappdata}\Jarvis');
end;

function EnvFile: String;
begin
  Result := DataDir + '\.env';
end;

{ The key saved by an earlier install (or typed into Jarvis > Settings), or '' if none. }
function ReadSavedKey: String;
var
  Content: AnsiString;
  S: String;
  P, E: Integer;
begin
  Result := '';
  if LoadStringFromFile(EnvFile, Content) then
  begin
    S := String(Content);
    P := Pos('GROQ_API_KEY=', S);
    if P > 0 then
    begin
      S := Copy(S, P + Length('GROQ_API_KEY='), Length(S));
      E := Pos(#13, S);
      if E = 0 then
        E := Pos(#10, S);
      if E > 0 then
        S := Copy(S, 1, E - 1);
      Result := Trim(S);
    end;
  end;
end;

{ True when this PC lacks Microsoft's Visual C++ runtime (2019 or newer), which the speech and
  hand-tracking libraries need. }
function VCRedistNeeded: Boolean;
var
  Installed, Bld: Cardinal;
begin
  Result := True;
  if RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) and (Installed = 1) then
    if RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Bld', Bld) then
      Result := (Bld < 30000);
end;

procedure InstallVCRedist;
var
  ResultCode: Integer;
begin
#ifdef HaveVCRedist
  if VCRedistNeeded then
  begin
    WizardForm.StatusLabel.Caption := 'Installing the Microsoft Visual C++ runtime (Windows may ask for permission)...';
    ExtractTemporaryFile('vc_redist.x64.exe');
    ShellExec('runas', ExpandConstant('{tmp}\vc_redist.x64.exe'), '/install /quiet /norestart', '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
  end;
#endif
end;

procedure OpenKeyLink(Sender: TObject);
var
  ErrorCode: Integer;
begin
  ShellExec('open', 'https://console.groq.com/keys', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

procedure InitializeWizard;
begin
  SavedKey := ReadSavedKey;

  { Always shown, right after the Welcome page - it can no longer be skipped. }
  KeyPage := CreateInputQueryPage(wpWelcome,
    'Enter your Groq API key',
    'Jarvis needs your Groq API key to understand and answer you.',
    'Paste your key below (right-click in the box > Paste, or press Ctrl+V). It is saved only on this PC and is used only to talk to Groq.');
  KeyPage.Add('Groq API key (starts with gsk_):', False);

  { Silent installs can pass it on the command line:  Jarvis-Setup.exe /VERYSILENT /KEY=gsk_... }
  if ExpandConstant('{param:KEY|}') <> '' then
    KeyPage.Values[0] := ExpandConstant('{param:KEY|}')
  else
    KeyPage.Values[0] := SavedKey;

  if SavedKey <> '' then
    KeyPage.SubCaptionLabel.Caption := 'A key saved by an earlier install was filled in for you. Click Next to keep it, or paste a different key.';

  KeyLink := TNewStaticText.Create(KeyPage);
  KeyLink.Parent := KeyPage.Surface;
  KeyLink.Caption := 'Don''t have a key yet? Get one free at console.groq.com/keys';
  KeyLink.Cursor := crHand;
  KeyLink.Font.Style := KeyLink.Font.Style + [fsUnderline];
  KeyLink.Font.Color := clBlue;
  KeyLink.OnClick := @OpenKeyLink;
  KeyLink.Left := KeyPage.Edits[0].Left;
  KeyLink.Top := KeyPage.Edits[0].Top + KeyPage.Edits[0].Height + ScaleY(12);
end;

{ Asks Groq whether the key works. Returns False if Groq could not be reached at all. }
function CheckKeyOnline(const Key: String; var StatusCode: Integer): Boolean;
var
  Http: Variant;
begin
  Result := False;
  StatusCode := 0;
  try
    Http := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Http.SetTimeouts(5000, 5000, 10000, 10000);
    Http.Open('GET', 'https://api.groq.com/openai/v1/models', False);
    Http.SetRequestHeader('Authorization', 'Bearer ' + Key);
    Http.SetRequestHeader('User-Agent', 'JarvisInstaller/1.0');
    Http.Send('');
    StatusCode := Http.Status;
    Result := True;
  except
    Result := False;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Key: String;
  Status: Integer;
begin
  Result := True;
  if CurPageID <> KeyPage.ID then
    Exit;

  Key := Trim(KeyPage.Values[0]);

  if Key = '' then
  begin
    MsgBox('Please paste your Groq API key to continue. Jarvis cannot work without it.', mbError, MB_OK);
    Result := False;
    Exit;
  end;

  if Pos(' ', Key) > 0 then
  begin
    MsgBox('The key contains a space. Please paste just the key (it starts with gsk_).', mbError, MB_OK);
    Result := False;
    Exit;
  end;

  if Pos('gsk_', Key) <> 1 then
  begin
    if MsgBox('Groq API keys start with "gsk_" and this one does not. Use it anyway?',
              mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := False;
      Exit;
    end;
  end;

  { Check the key with Groq so a typo is caught now, not after install. }
  WizardForm.Cursor := crHourGlass;
  try
    if CheckKeyOnline(Key, Status) then
    begin
      if Status = 401 then
      begin
        MsgBox('Groq rejected this API key. Please check it was copied completely, or create a new one at console.groq.com/keys.', mbError, MB_OK);
        Result := False;
      end;
    end
    else
    begin
      if MsgBox('Could not reach Groq to check the key (no internet connection?). Continue anyway?',
                mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  finally
    WizardForm.Cursor := crDefault;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Key: String;
begin
  if CurStep = ssPostInstall then
  begin
    InstallVCRedist;
    Key := Trim(KeyPage.Values[0]);
    if Key <> '' then
    begin
      ForceDirectories(DataDir);
      SaveStringToFile(EnvFile, 'GROQ_API_KEY=' + Key + #13#10, False);
    end;
  end;
end;
