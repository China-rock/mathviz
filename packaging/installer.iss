; MathViz 安装脚本（Inno Setup 6）
;
; 用法：先跑 packaging\build_all.py 产出 dist\MathViz，再编译本文件：
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
; 产物：dist\MathViz-1.0-Setup.exe
;
; 说明两点：
;   · 装到 Program Files 是安全的 —— 渲染工作目录固定在 %LOCALAPPDATA%\MathVizWork
;     （无空格），成片、日志、Key 也都在用户目录，不会往只读的程序目录里写。
;   · LaTeX 不在安装包里（不是 pip 包，几百 MB 且需联网补宏包），
;     所以安装结束时检测一次，缺就引导去装。

#define MyAppName "MathViz"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "MathViz"
#define MyAppURL "https://miktex.org/download"
#define MyAppExeName "MathViz.exe"
#define DistDir "..\dist\MathViz"

[Setup]
AppId={{B7F4E2A1-9C3D-4E58-A6F0-1D2C8B5E7A31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; DisableDirPage 的默认值是 auto —— 一旦检测到旧版本的安装目录，就会直接跳过
; 「选择安装位置」页，用户想改装到别的盘就没有机会改。这里固定为 no：
; 首次安装、升级安装都一定显示路径页（升级时默认填上次的目录，回车即沿用）。
DisableDirPage=no
; 升级时以注册表里记录的旧目录作为默认值（仍可在路径页里改）。
UsePreviousAppDir=yes
LicenseFile=..\LICENSE
SetupIconFile=..\assets\mathviz-icon-v2.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
; 两个 _internal 里有大量重复文件（numpy / scipy / manim 各一份），
; 固态压缩能让重复内容几乎不占体积 —— 这一项是体积的关键。
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
DiskSpanning=no
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; 默认按整机装（需要管理员），没权限时可以切成"仅为我安装"
PrivilegesRequiredOverridesAllowed=dialog
PrivilegesRequired=admin
OutputBaseFilename=MathViz-{#MyAppVersion}-Setup
OutputDir=..\dist
ChangesAssociations=no

[Languages]
; 官方版 Inno Setup 不带中文语言包，这份是项目里自己翻译的（基于 Default.isl）。
Name: "chinesesimp"; MessagesFile: "languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "在桌面上创建快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked

[Files]
Source: "{#DistDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistDir}\manim_worker.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DistDir}\_internal_worker\*"; DestDir: "{app}\_internal_worker"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 不带 skipifsilent：程序内更新走的就是静默安装，装完要自动把 MathViz 拉起来，
; 否则用户点完「立即更新」就只剩一个空桌面。
Filename: "{app}\{#MyAppExeName}"; Description: "现在启动 {#MyAppName}"; \
    Flags: nowait postinstall

[Code]
function HasTeX(): Boolean;
begin
  Result := FileExists(ExpandConstant('{pf}\MiKTeX\miktex\bin\x64\latex.exe'))
        or FileExists(ExpandConstant('{cf}\MiKTeX\miktex\bin\x64\latex.exe'))
        or DirExists(ExpandConstant('{localappdata}\Programs\MiKTeX\miktex\bin\x64'))
        or DirExists(ExpandConstant('C:\MiKTeX\miktex\bin\x64'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ErrorCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    // 静默安装（程序内更新）时不开口提问 —— 那个 MsgBox 会把无人值守的
    // 更新挂住；缺 LaTeX 的引导留给首次手动安装的向导，以及程序内首次渲染。
    if (not HasTeX()) and (not WizardSilent()) then
    begin
      if MsgBox('没有检测到 LaTeX（MiKTeX）。' + #13#10 + #13#10 +
                '数学公式渲染依赖它，首次渲染前需要装一次（约 500 MB，装完重启本软件）。' + #13#10 +
                '也可以先跳过，等第一次点渲染时软件会再提示。' + #13#10 + #13#10 +
                '现在打开 MiKTeX 下载页吗？',
                mbConfirmation, MB_YESNO) = IDYES then
      begin
        ShellExec('open', '{#MyAppURL}', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
      end;
    end;
  end;
end;
