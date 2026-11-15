@echo off
rem Build chunk.apk: configure server URL, cap sync, then gradle assembleRelease.
rem Output: apk\android\app\build\outputs\apk\release\app-release.apk
rem Server URL: "node configure.mjs" reads server.config.json (see docs/DEPLOY.md).
rem JAVA_HOME (JDK 21) and ANDROID_HOME come from your environment;
rem the paths below are only used when they exist on this machine.
if exist "C:\Program Files\Eclipse Adoptium\jdk-21.0.12.101-hotspot" set "JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-21.0.12.101-hotspot"
if exist "E:\android-sdk" set "ANDROID_HOME=E:\android-sdk"
if exist "E:\android-sdk\gradle-home" set "GRADLE_USER_HOME=E:\android-sdk\gradle-home"
cd /d "%~dp0"
call node configure.mjs
if errorlevel 1 exit /b 1
call node node_modules\@capacitor\cli\bin\capacitor sync android
if errorlevel 1 exit /b 1
cd android
call .\gradlew.bat assembleRelease --no-daemon
if errorlevel 1 exit /b 1
echo.
echo APK built: %~dp0android\app\build\outputs\apk\release\app-release.apk
