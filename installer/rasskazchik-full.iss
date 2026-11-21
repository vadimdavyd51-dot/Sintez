#define AppName "Рассказчик у камина"
#define AppVer "1.0.0"

[Setup]
AppId={{B7D6A3A2-5C2B-4E0F-9B8E-6A1F0C5D2E11}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=Sintez
DefaultDirName={localappdata}\Rasskazchik
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=Rasskazchik-Full-Setup
Compression=zip/1
SolidCompression=no
DiskSpanning=yes
DiskSliceSize=1900000000
SlicesPerDisk=1
WizardStyle=modern

[Languages]
#if FileExists(CompilerPath + "Languages\Russian.isl")
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
#else
Name: "english"; MessagesFile: "compiler:Default.isl"
#endif

[Dirs]
Name: "{app}\Озвучка"

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autodesktop}\Рассказчик"; Filename: "{app}\run.bat"; WorkingDir: "{app}"
Name: "{autodesktop}\Рассказчик: готовые озвучки"; Filename: "{app}\Озвучка"
Name: "{autoprograms}\Рассказчик\Рассказчик"; Filename: "{app}\run.bat"; WorkingDir: "{app}"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\__pycache__"
