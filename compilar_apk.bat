@echo off
rem Genera FutBot.apk (nueva version de la app del celular) con los datos de hoy incluidos
rem y, si el celular esta conectado por USB (depuracion USB activa), la instala encima.
rem La ruta real tiene "U con tilde" y Dart/Gradle fallan con ella: se compila desde la unidad virtual R:.
cd /d "%~dp0"
if not exist R:\ subst R: "%~dp0."
python -P bot.py exportar
xcopy /e /y /i publicar\paquete.json app_movil\assets\paquete\ >nul
xcopy /e /y /i publicar\escudos app_movil\assets\paquete\escudos >nul
set JAVA_TOOL_OPTIONS=-Djavax.net.ssl.trustStore=C:/Users/Asus/develop/certificados/cacerts-con-avast -Djavax.net.ssl.trustStorePassword=changeit
pushd R:\app_movil
call C:\Users\Asus\develop\flutter\bin\flutter.bat build apk --release
popd
copy /y R:\app_movil\build\app\outputs\flutter-apk\app-release.apk FutBot.apk
echo.
set ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe
"%ADB%" get-state >nul 2>&1
if errorlevel 1 (
  echo FutBot.apk lista. No veo el celular: conectalo por USB con la depuracion USB activa y vuelve a abrir este archivo,
  echo o copia FutBot.apk al celular e instalala encima. Tus datos se conservan.
) else (
  "%ADB%" install -r FutBot.apk && echo Listo: FutBot actualizado en el celular. Tus datos se conservan.
)
pause
