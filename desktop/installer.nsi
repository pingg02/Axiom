; Reasonix Windows Installer (NSIS)
; 编译: makensis installer.nsi
; 构建前需先执行:
;   cd reasonix-py && python -m PyInstaller reasonix_min.spec
;   cd reasonix-java && mvn package -DskipTests

!define PRODUCT_NAME "Reasonix"
!define PRODUCT_VERSION "0.1.0"
!define PRODUCT_PUBLISHER "Reasonix"

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "Reasonix-windows-amd64-installer.exe"
InstallDir "$PROFILE\reasonix"
RequestExecutionLevel user

Section "Install"
  SetOutPath "$INSTDIR"
  
  ; Python 运行环境 (PyInstaller exe)
  File /r "..\reasonix-py\dist\reasonix.exe"
  
  ; Java 安全服务 (Spring Boot fatjar)
  File /r "..\reasonix-java\target\reasonix-security.jar"
  
  ; React 前端 + Electron 桌面
  File /r "..\desktop\*.*"
  
  ; 启动脚本
  File "..\start_reasonix_full.cmd"
  
  ; 创建卸载器
  WriteUninstaller "$INSTDIR\uninstall.exe"
  
  ; 创建快捷方式
  CreateDirectory "$SMPROGRAMS\Reasonix"
  CreateShortCut "$SMPROGRAMS\Reasonix\Reasonix.lnk" "$INSTDIR\start_reasonix_full.cmd"
  CreateShortCut "$SMPROGRAMS\Reasonix\Uninstall.lnk" "$INSTDIR\uninstall.exe"
  
  ; 添加到 PATH
  EnVar::AddValue "PATH" "$INSTDIR"
SectionEnd

Section "Uninstall"
  RMDir /r "$INSTDIR"
  RMDir /r "$SMPROGRAMS\Reasonix"
  EnVar::DeleteValue "PATH" "$INSTDIR"
SectionEnd
