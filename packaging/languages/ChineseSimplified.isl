; *** Inno Setup 6 简体中文消息 ***
; 由 MathViz 项目基于官方 Default.isl 翻译生成
;
; To download user-contributed translations of this file, go to:
;   https://jrsoftware.org/files/istrans/
;
; Note: When translating this text, do not add periods (.) to the end of
; messages that didn't have them already, because on those messages Inno
; Setup adds the periods automatically (appending a period would result in
; two periods being displayed).

[LangOptions]
; The following three entries are very important. Be sure to read and
; understand the '[LangOptions] section' topic in the help file.
LanguageName=简体中文
LanguageID=$0804
; LanguageCodePage should always be set if possible, even if this file is Unicode
; For English it's set to zero anyway because English only uses ASCII characters
LanguageCodePage=936
; If the language you are translating to requires special font faces or
; sizes, uncomment any of the following entries and change them accordingly.
;DialogFontName=
;DialogFontSize=9
;DialogFontBaseScaleWidth=7
;DialogFontBaseScaleHeight=15
;WelcomeFontName=Segoe UI
;WelcomeFontSize=14

[Messages]

; *** Application titles
SetupAppTitle=安装 - %1
SetupWindowTitle=安装 - %1
UninstallAppTitle=卸载
UninstallAppFullTitle=卸载 - %1

; *** Misc. common
InformationTitle=信息
ConfirmTitle=确认
ErrorTitle=错误

; *** SetupLdr messages
SetupLdrStartupMessage=正在准备安装向导，请稍候...
LdrCannotCreateTemp=无法创建临时文件。安装已中止。
LdrCannotExecTemp=无法执行临时目录中的文件。安装已中止。
HelpTextNote=

; *** Startup error messages
LastErrorMessage=%1.%n%nError %2: %3
SetupFileMissing=安装目录中缺少文件 %1。请修正此问题或获取新的安装包。
SetupFileCorrupt=安装文件已损坏。请获取新的安装包。
SetupFileCorruptOrWrongVer=安装文件已损坏，或与本次安装的版本不符。请获取新的安装包。
InvalidParameter=命令行参数无效:%n%n%1
SetupAlreadyRunning=安装程序已在运行。%n%n请先关闭现有的安装程序，然后再试一次。
WindowsVersionNotSupported=此程序不支持当前版本的 Windows。
WindowsServicePackRequired=此程序需要 %1 的 Service Pack %2 或更高版本。
NotOnThisPlatform=此程序无法在 %1 上运行。
OnlyOnThisPlatform=此程序只能在 %1 上运行。
OnlyOnTheseArchitectures=此程序无法安装在当前的处理器体系结构上。
WinVersionTooLowError=此程序需要 %1 或更高版本。
WinVersionTooHighError=此程序无法安装在 %1 或更高版本上。
AdminPrivilegesRequired=安装此程序时必须以管理员身份登录。
PowerUserPrivilegesRequired=安装此程序时必须以管理员或高级用户身份登录。
SetupAppRunningError=安装程序检测到 %1 正在运行。%n%n请立即关闭它的所有实例，然后单击“确定”继续，或单击“取消”退出。
UninstallAppRunningError=卸载程序检测到 %1 正在运行。%n%n请立即关闭它的所有实例，然后单击“确定”继续，或单击“取消”退出。

; *** Startup questions
PrivilegesRequiredOverrideTitle=选择安装模式
PrivilegesRequiredOverrideInstruction=请选择安装模式
PrivilegesRequiredOverrideText1=单击“为所有用户安装”可将 %1 安装给本机的所有用户，或单击“仅为我安装”只安装到您的用户账户。
PrivilegesRequiredOverrideText2=单击“为所有用户安装”可将 %1 安装给本机的所有用户，或单击“仅为我安装”只安装到您的用户账户（推荐）。
PrivilegesRequiredOverrideAllUsers=为所有用户安装(&A)
PrivilegesRequiredOverrideAllUsersRecommended=为所有用户安装(&A)（推荐）
PrivilegesRequiredOverrideCurrentUser=仅为我安装(&M)
PrivilegesRequiredOverrideCurrentUserRecommended=仅为我安装(&M)（推荐）

; *** Misc. errors
ErrorCreatingDir=无法创建文件夹“%1”
ErrorTooManyFilesInDir=无法在文件夹“%1”中创建文件，因为该文件夹中的文件过多

; *** Setup common messages
ExitSetupTitle=退出安装程序
ExitSetupMessage=安装尚未完成。如果现在退出，程序将不会被安装。%n%n您可以稍后再运行安装程序以完成安装。%n%n退出安装程序吗？
AboutSetupMenuItem=关于安装程序(&A)...
AboutSetupTitle=关于安装程序
AboutSetupMessage=%1 version %2%n%3%n%n%1 home page:%n%4
AboutSetupNote=
TranslatorNote=

; *** Buttons
ButtonBack=< 上一步(&B)
ButtonNext=下一步(&N) >
ButtonInstall=安装(&I)
ButtonOK=确定
ButtonCancel=取消
ButtonYes=是(&Y)
ButtonYesToAll=全部是(&A)
ButtonNo=否(&N)
ButtonNoToAll=全部否(&O)
ButtonFinish=完成(&F)
ButtonBrowse=浏览(&R)...
ButtonWizardBrowse=浏览文件夹...
ButtonNewFolder=新建文件夹(&M)

; *** "Select Language" dialog messages
SelectLanguageTitle=选择安装语言
SelectLanguageLabel=请选择安装时要使用的语言。

; *** Common wizard text
ClickNext=单击“下一步”继续，或单击“取消”退出安装程序。
BeveledLabel=
BrowseDialogTitle=浏览文件夹
BrowseDialogLabel=请选择文件夹，然后单击“确定”。
NewFolderName=新建文件夹

; *** "Welcome" wizard page
WelcomeLabel1=欢迎使用 [name] 安装向导
WelcomeLabel2=本向导将把 [name/ver] 安装到您的计算机中。%n%n建议您在继续之前关闭所有其它应用程序。

; *** "Password" wizard page
WizardPassword=密码
PasswordLabel1=此安装程序受密码保护。
PasswordLabel3=请输入密码，然后单击“下一步”继续。密码区分大小写。
PasswordEditLabel=密码(&P):
IncorrectPassword=您输入的密码不正确，请重新输入。

; *** "License Agreement" wizard page
WizardLicense=许可协议
LicenseLabel=请在继续安装之前仔细阅读以下许可协议条款。
LicenseLabel3=请仔细阅读以下许可协议。您必须接受本协议条款才能继续安装。
LicenseAccepted=我接受协议(&A)
LicenseNotAccepted=我不接受协议(&D)

; *** "Information" wizard pages
WizardInfoBefore=信息
InfoBeforeLabel=请在继续之前阅读以下重要信息。
InfoBeforeClickLabel=阅读完毕后，单击“下一步”继续。
WizardInfoAfter=信息
InfoAfterLabel=请在继续之前阅读以下重要信息。
InfoAfterClickLabel=阅读完毕后，单击“下一步”继续。

; *** "User Information" wizard page
WizardUserInfo=用户信息
UserInfoDesc=请输入您的信息。
UserInfoName=用户名(&U):
UserInfoOrg=组织(&O):
UserInfoSerial=序列号(&S):
UserInfoNameRequired=您必须输入用户名。

; *** "Select Destination Location" wizard page
WizardSelectDir=选择目标位置
SelectDirDesc=您想将 [name] 安装到何处？
SelectDirLabel3=安装程序将把 [name] 安装到以下文件夹中。%n%n要安装到此文件夹，请单击“下一步”。
SelectDirBrowseLabel=要安装到其它文件夹，请单击“浏览”并选择该文件夹。
DiskSpaceGBLabel=所需空间: [gb] GB
DiskSpaceMBLabel=所需空间: [mb] MB
CannotInstallToNetworkDrive=安装程序无法安装到网络驱动器。
CannotInstallToUNCPath=安装程序无法安装到 UNC 路径。
InvalidPath=您必须输入完整路径，包含驱动器号；例如:%n%nC:\APP%n%n或如下格式的 UNC 路径:%n%n\\server\share
InvalidDrive=您选择的驱动器或 UNC 共享不存在或无法访问。请选择其它位置。
DiskSpaceWarningTitle=磁盘空间不足
DiskSpaceWarning=安装程序至少需要 %1 KB 可用空间才能安装，但所选驱动器上只有 %2 KB 可用。%n%n是否仍要继续？
DirNameTooLong=文件夹名或路径过长。
InvalidDirName=文件夹名无效。
BadDirName32=文件夹名不能包含以下任何字符:%n%n%1
DirExistsTitle=文件夹已存在
DirExists=以下文件夹已存在:%n%n%1%n%n是否仍要安装到此文件夹？
DirDoesntExistTitle=文件夹不存在
DirDoesntExist=文件夹 %1 不存在。是否创建此文件夹？

; *** "Select Components" wizard page
WizardSelectComponents=选择组件
SelectComponentsDesc=您想安装哪些组件？
SelectComponentsLabel2=请选择要安装的组件；清除不想安装的组件。单击“下一步”继续。
FullInstallation=完整安装
; if possible don't translate 'Compact' as 'Minimal' (I mean 'Minimal' in your language)
CompactInstallation=精简安装
CustomInstallation=自定义安装
NoUninstallWarningTitle=无法卸载
NoUninstallWarning=Setup has detected that the following components are already installed on your computer:%n%n%1%n%nDeselecting these components will not uninstall them.%n%nWould you like to continue anyway?
ComponentSize1=此组件需要约 %1 KB 磁盘空间。
ComponentSize2=这些组件需要约 %1 KB 磁盘空间。
ComponentsDiskSpaceGBLabel=所选组件至少需要 [gb] GB 磁盘空间。
ComponentsDiskSpaceMBLabel=所选组件至少需要 [mb] MB 磁盘空间。

; *** "Select Additional Tasks" wizard page
WizardSelectTasks=选择附加任务
SelectTasksDesc=您想执行哪些附加任务？
SelectTasksLabel2=请选择安装 [name] 时要执行的附加任务，然后单击“下一步”。

; *** "Select Start Menu Folder" wizard page
WizardSelectProgramGroup=选择开始菜单文件夹
SelectStartMenuFolderDesc=安装程序应在哪里创建程序的快捷方式？
SelectStartMenuFolderLabel3=安装程序将在以下开始菜单文件夹中创建快捷方式。%n%n要继续，请单击“下一步”。
SelectStartMenuFolderBrowseLabel=要创建到其它文件夹，请单击“浏览”并选择该文件夹。
MustEnterGroupName=您必须输入文件夹名。
GroupNameTooLong=文件夹名或路径过长。
InvalidGroupName=文件夹名无效。
BadGroupName=文件夹名不能包含以下任何字符:%n%n%1
NoProgramGroupCheck2=不创建开始菜单文件夹(&N)

; *** "Ready to Install" wizard page
WizardReady=准备安装
ReadyLabel1=安装程序现已准备好将 [name] 安装到您的计算机中。
ReadyLabel2a=单击“安装”继续安装，或单击“上一步”修改设置。
ReadyLabel2b=单击“安装”继续安装。
ReadyMemoUserInfo=用户信息:
ReadyMemoDir=目标位置:
ReadyMemoType=安装类型:
ReadyMemoComponents=组件:
ReadyMemoGroup=开始菜单文件夹:
ReadyMemoTasks=附加任务:

; *** TDownloadWizardPage wizard page and DownloadTemporaryFile
DownloadingLabel2=Downloading files...
ButtonStopDownload=&Stop download
StopDownload=Are you sure you want to stop the download?
ErrorDownloadAborted=Download aborted
ErrorDownloadFailed=Download failed: %1 %2
ErrorDownloadSizeFailed=Getting size failed: %1 %2
ErrorProgress=Invalid progress: %1 of %2
ErrorFileSize=Invalid file size: expected %1, found %2

; *** TExtractionWizardPage wizard page and ExtractArchive
ExtractingLabel=Extracting files...
ButtonStopExtraction=&Stop extraction
StopExtraction=Are you sure you want to stop the extraction?
ErrorExtractionAborted=Extraction aborted
ErrorExtractionFailed=Extraction failed: %1

; *** Archive extraction failure details
ArchiveIncorrectPassword=The password is incorrect
ArchiveIsCorrupted=The archive is corrupted
ArchiveUnsupportedFormat=The archive format is unsupported

; *** "Preparing to Install" wizard page
WizardPreparing=准备安装
PreparingDesc=安装程序正在准备安装 [name]。
PreviousInstallNotCompleted=上一次安装未完成。您需要重启计算机才能完成那次安装。%n%n重启后，请再次运行安装程序以完成 [name] 的安装。
CannotContinue=安装程序无法继续。请重启计算机后再运行一次安装程序。
ApplicationsFound=以下应用程序正在使用需要由安装程序更新的文件:%n
ApplicationsFound2=以下应用程序正在使用需要重启计算机后才能替换的文件:%n
CloseApplications=建议允许安装程序自动关闭这些应用程序。关闭后，安装程序才能继续。
DontCloseApplications=不要关闭这些应用程序(&D)
ErrorCloseApplications=安装程序无法自动关闭所有应用程序。建议在继续之前关闭所有使用需更新文件的应用程序。
PrepareToInstallNeedsRestart=安装程序需要重启计算机才能继续。重启后，请再次运行安装程序以完成 [name] 的安装。

; *** "Installing" wizard page
WizardInstalling=正在安装
InstallingLabel=请稍候，安装程序正在将 [name] 安装到您的计算机中。

; *** "Setup Completed" wizard page
FinishedHeadingLabel=[name] 安装完成
FinishedLabelNoIcons=安装程序已在您的计算机中安装 [name]。
FinishedLabel=安装程序已在您的计算机中安装 [name]。单击“完成”退出安装程序。
ClickFinish=单击“完成”退出安装程序。
FinishedRestartLabel=要完成 [name] 的安装，必须重启计算机。是否立即重启？
FinishedRestartMessage=要完成 [name] 的安装，必须重启计算机。%n%n是否立即重启？
ShowReadmeCheck=是，我想查看自述文件
YesRadio=是(&Y)
NoRadio=否(&N)
; used for example as 'Run MyProg.exe'
RunEntryExec=运行 %1
; used for example as 'View Readme.txt'
RunEntryShellExec=打开 %1

; *** "Setup Needs the Next Disk" stuff
ChangeDiskTitle=请插入磁盘 %1
SelectDiskLabel2=请插入磁盘 %1，然后单击“确定”。%n%n如果此磁盘中的文件位于其它文件夹，请输入正确路径或单击“浏览”。
PathLabel=路径:
FileNotInDir2=文件“%1”不在“%2”中。请插入正确的磁盘或选择其它文件夹。
SelectDirectoryLabel=请选择下一个磁盘的位置。

; *** Installation phase messages
SetupAborted=安装尚未完成。%n%n如再次运行安装程序，将从上次中断处继续。%n%n单击“取消”退出安装程序。
AbortRetryIgnoreSelectAction=单击“重试”再试一次，单击“忽略”继续，或单击“取消”中止安装。
AbortRetryIgnoreRetry=重试(&T)
AbortRetryIgnoreIgnore=忽略(&I)
AbortRetryIgnoreCancel=取消
RetryCancelSelectAction=单击“重试”再试一次，或单击“取消”中止安装。
RetryCancelRetry=重试(&T)
RetryCancelCancel=取消

; *** Installation status messages
StatusClosingApplications=正在关闭应用程序...
StatusCreateDirs=正在创建文件夹...
StatusExtractFiles=正在解压文件...
StatusDownloadFiles=正在下载文件...
StatusCreateIcons=正在创建快捷方式...
StatusCreateIniEntries=正在创建 INI 条目...
StatusCreateRegistryEntries=正在创建注册表条目...
StatusRegisterFiles=正在注册文件...
StatusSavingUninstall=正在保存卸载信息...
StatusRunProgram=正在完成安装...
StatusRestartingApplications=正在重启应用程序...
StatusRollback=正在回滚更改...

; *** Misc. errors
ErrorInternal2=内部错误 %1
ErrorFunctionFailedNoCode=%1 失败
ErrorFunctionFailed=%1 失败；代码 %2
ErrorFunctionFailedWithMessage=%1 失败；代码 %2。%n%3
ErrorExecutingProgram=无法执行文件:%n%1

; *** Registry errors
ErrorRegOpenKey=Error opening registry key:%n%1\%2
ErrorRegCreateKey=Error creating registry key:%n%1\%2
ErrorRegWriteKey=Error writing to registry key:%n%1\%2

; *** INI errors
ErrorIniEntry=Error creating INI entry in file "%1".

; *** File copying errors
FileAbortRetryIgnoreSkipNotRecommended=单击“重试”再试一次，单击“忽略”跳过此文件，或单击“取消”中止安装。
FileAbortRetryIgnoreIgnoreNotRecommended=单击“忽略”跳过此文件（不推荐），或单击“取消”中止安装。
SourceIsCorrupted=源文件已损坏
SourceDoesntExist=源文件“%1”不存在
SourceVerificationFailed=Verification of the source file failed: %1
VerificationSignatureDoesntExist=The signature file "%1" does not exist
VerificationSignatureInvalid=The signature file "%1" is invalid
VerificationKeyNotFound=The signature file "%1" uses an unknown key
VerificationFileNameIncorrect=The name of the file is incorrect
VerificationFileTagIncorrect=The tag of the file is incorrect
VerificationFileSizeIncorrect=The size of the file is incorrect
VerificationFileHashIncorrect=The hash of the file is incorrect
ExistingFileReadOnly2=无法替换现有文件 %1，因为它已被设为只读。%n%n单击“重试”移除只读属性并再试一次，单击“忽略”跳过此文件，或单击“取消”中止安装。
ExistingFileReadOnlyRetry=重试(&T)
ExistingFileReadOnlyKeepExisting=忽略(&I)
ErrorReadingExistingDest=读取现有文件时出错:
FileExistsSelectAction=文件已存在。%n%n安装程序是否应该覆盖它？
FileExists2=文件 %1 已存在。%n%n安装程序是否应该覆盖它？
FileExistsOverwriteExisting=是，覆盖此文件(&O)
FileExistsKeepExisting=否，保留此文件(&K)
FileExistsOverwriteOrKeepAll=对所有此类冲突都执行相同操作(&D)
ExistingFileNewerSelectAction=目标中的现有文件比安装程序中的文件新。%n%n安装程序是否应该覆盖它？
ExistingFileNewer2=文件 %1 已存在，且比安装程序中的文件新。%n%n安装程序是否应该覆盖它？
ExistingFileNewerOverwriteExisting=是，覆盖较新的文件(&O)
ExistingFileNewerKeepExisting=否，保留较新的文件(&K)
ExistingFileNewerOverwriteOrKeepAll=对所有此类冲突都执行相同操作(&D)
ErrorChangingAttr=无法更改现有文件的属性:
ErrorCreatingTemp=无法在安装目录中创建临时文件:
ErrorReadingSource=无法读取源文件:
ErrorCopying=无法复制文件:
ErrorDownloading=An error occurred while trying to download a file:
ErrorExtracting=An error occurred while trying to extract an archive:
ErrorReplacingExistingFile=无法替换现有文件:
ErrorRestartReplace=RestartReplace failed:
ErrorRenamingTemp=无法重命名安装目录中的临时文件:
ErrorRegisterServer=无法注册 DLL/OCX: %1
ErrorRegSvr32Failed=RegSvr32 失败，退出码 %1
ErrorRegisterTypeLib=无法注册类型库: %1

; *** Uninstall display name markings
; used for example as 'My Program (32-bit)'
UninstallDisplayNameMark=%1 (%2)
; used for example as 'My Program (32-bit, All users)'
UninstallDisplayNameMarks=%1 (%2)
UninstallDisplayNameMark32Bit=32 位
UninstallDisplayNameMark64Bit=64 位
UninstallDisplayNameMarkAllUsers=所有用户
UninstallDisplayNameMarkCurrentUser=当前用户

; *** Post-installation errors
ErrorOpeningReadme=打开自述文件时出错。
ErrorRestartingComputer=重启计算机时出错。

; *** Uninstaller messages
UninstallNotFound=无法找到 %1 的卸载信息。它可能已被卸载。
UninstallOpenError=无法打开卸载信息文件“%1”。无法卸载 %2。
UninstallUnsupportedVer=卸载日志文件“%2”的格式不被此版本的卸载程序识别。无法卸载 %1
UninstallUnknownEntry=卸载日志中存在未知条目 (%1)
ConfirmUninstall=您确定要完全卸载 %1 及其所有组件吗？
UninstallOnlyOnWin64=此安装只能在 64 位 Windows 上卸载。
OnlyAdminCanUninstall=只有具有管理员权限的用户才能卸载此程序。
UninstallStatusLabel=请稍候，正在从您的计算机中卸载 %1。
UninstalledAll=%1 已成功从您的计算机中卸载。
UninstalledMost=%1 卸载完成。%n%n部分元素未能卸载，您可以手动删除。
UninstalledAndNeedsRestart=要完成 %1 的卸载，必须重启计算机。%n%n是否立即重启？
UninstallDataCorrupted=文件“%1”已损坏。无法卸载 %2。

; *** Uninstallation phase messages
ConfirmDeleteSharedFileTitle=删除共享文件？
ConfirmDeleteSharedFile2=The system indicates that the following shared file is no longer in use by any programs. Would you like for Uninstall to remove this shared file?%n%nIf any programs are still using this file and it is removed, those programs may not function properly. If you are unsure, choose No. Leaving the file on your system will not cause any harm.
SharedFileNameLabel=文件名:
SharedFileLocationLabel=位置:
WizardUninstalling=正在卸载
StatusUninstalling=正在卸载...

; *** Shutdown block reasons
ShutdownBlockReasonInstallingApp=正在安装 %1
ShutdownBlockReasonUninstallingApp=正在卸载 %1

; The custom messages below aren't used by Setup itself, but if you make
; use of them in your scripts, you'll want to translate them.

[CustomMessages]

NameAndVersion=%1 version %2
AdditionalIcons=Additional shortcuts:
CreateDesktopIcon=Create a &desktop shortcut
CreateQuickLaunchIcon=Create a &Quick Launch shortcut
ProgramOnTheWeb=%1 on the Web
UninstallProgram=Uninstall %1
LaunchProgram=Launch %1
AssocFileExtension=&Associate %1 with the %2 file extension
AssocingFileExtension=Associating %1 with the %2 file extension...
AutoStartProgramGroupDescription=Startup:
AutoStartProgram=Automatically start %1
AddonHostProgramNotFound=%1 could not be located in the folder you selected.%n%nDo you want to continue anyway?
