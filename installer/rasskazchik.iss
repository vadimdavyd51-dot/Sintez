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
OutputDir=Output
OutputBaseFilename=Rasskazchik-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no

[Languages]
#if FileExists(CompilerPath + "Languages\Russian.isl")
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
#else
Name: "english"; MessagesFile: "compiler:Default.isl"
#endif

[Dirs]
Name: "{app}\Озвучка"

[Files]
Source: "..\app\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autodesktop}\Рассказчик"; Filename: "{app}\run.bat"; WorkingDir: "{app}"
Name: "{autodesktop}\Рассказчик: готовые озвучки"; Filename: "{app}\Озвучка"
Name: "{autoprograms}\Рассказчик\Рассказчик"; Filename: "{app}\run.bat"; WorkingDir: "{app}"
Name: "{autoprograms}\Рассказчик\Рассказчик: доустановить компоненты"; Filename: "{app}\install.bat"; WorkingDir: "{app}"

[Run]
Filename: "{app}\install.bat"; WorkingDir: "{app}"; StatusMsg: "Устанавливаю компоненты и скачиваю модели (15-30 минут)..."; Flags: waitUntilTerminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\venv"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\__pycache__"
