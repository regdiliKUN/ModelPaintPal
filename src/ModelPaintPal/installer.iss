; Inno Setup 脚本 —— 生成 Windows 安装包（可选）
; 用法：先 `python scripts/build.py`，再 `ISCC.exe installer.iss`
; 需要安装 Inno Setup 6：https://jrsoftware.org/isinfo.php

#define MyAppName "ModelPaintPal"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "ModelPaintPal"
#define MyAppURL "https://github.com/"
#define MyAppExeName "ModelPaintPal.exe"
#define MyAppDirName "ModelPaintPal"
; 便携版目录（由 scripts/build.py 生成）
#define SourceDir "dist\ModelPaintPal"

[Setup]
AppId={{8F2C1A55-3D4E-4B7A-9C21-5E6D7A8B9C01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppDirName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE
OutputDir=dist\Installer
OutputBaseFilename={#MyAppName}-Setup-{#MyAppVersion}
SetupIconFile=app\resources\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 便携版目录整体安装；注意不包含 portable.marker（安装模式数据写入 %APPDATA%）
Source: "{#SourceDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs createallsubdirs; Check: DirExists('{#SourceDir}\docs')
Source: "{#SourceDir}\README.md"; DestDir: "{app}"; Flags: ignoreversion; Check: FileExists('{#SourceDir}\README.md')
Source: "{#SourceDir}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion; Check: FileExists('{#SourceDir}\LICENSE')

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
