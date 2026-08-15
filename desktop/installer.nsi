; Axiom Windows Installer (NSIS)
; 编译: makensis installer.nsi
; 构建前需先执行:
;   cd reasonix-py && python -m PyInstaller reasonix_min.spec
;   cd reasonix-java && mvn package -DskipTests
; 注意: electron-builder 的 "Axiom Setup <version>.exe" 才是正式安装包;
;       本 legacy NSIS 仅保留给旧版 CLI 启动方式, 与产品版本保持一致。

!define PRODUCT_NAME "Axiom"
!define PRODUCT_VERSION "0.2.1"
!define PRODUCT_PUBLISHER "Axiom"

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "Axiom-windows-amd64-installer.exe"
InstallDir "$PROFILE\axiom"
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
  CreateDirectory "$SMPROGRAMS\Axiom"
  CreateShortCut "$SMPROGRAMS\Axiom\Axiom.lnk" "$INSTDIR\start_reasonix_full.cmd"
  CreateShortCut "$SMPROGRAMS\Axiom\Uninstall.lnk" "$INSTDIR\uninstall.exe"
SectionEnd

Section "Uninstall"
  RMDir /r "$INSTDIR"
  RMDir /r "$SMPROGRAMS\Axiom"
SectionEnd
