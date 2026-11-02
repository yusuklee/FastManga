; FastManga 설치 파일 (Inno Setup). build/build.py 가 /DVersion=... 로 컴파일한다
#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{7E1F0B2A-5C4D-4B8E-9A61-3F0A57C2D9E4}
AppName=FastManga
AppVersion={#Version}
AppPublisher=yusuklee
AppPublisherURL=https://github.com/yusuklee/FastManga
DefaultDirName={localappdata}\Programs\FastManga
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Install-FastManga
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\icon.ico
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\FastManga\app\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "icon.ico"; DestDir: "{app}"

[Icons]
Name: "{autoprograms}\FastManga"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launch.py"""; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{autodesktop}\FastManga"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launch.py"""; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launch.py"""; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,FastManga}"; Flags: nowait postinstall skipifsilent

; 앱이 실행 중에 만든 것(패키지·모델·캐시·로그)은 제거 때 같이 지운다. 프로젝트는 물어보고 지운다
[UninstallDelete]
Type: filesandordirs; Name: "{app}\pylib"
Type: filesandordirs; Name: "{app}\pylib_models"
Type: filesandordirs; Name: "{app}\hf"
Type: filesandordirs; Name: "{app}\tmp"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\webview"
Type: filesandordirs; Name: "{app}\llama"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\Process\__pycache__"
Type: filesandordirs; Name: "{app}\fonts\__pycache__"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Dir := ExpandConstant('{app}\projects');
    if DirExists(Dir) then
      if MsgBox('Delete your FastManga projects too?' + #13#10 + Dir, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Dir, True, True, True);
    if DirExists(ExpandConstant('{app}')) then
      RemoveDir(ExpandConstant('{app}'));
  end;
end;
