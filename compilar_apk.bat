@echo off
rem Actualiza la app del celular por USB:
rem  1) trae lo que aprendio el celular (capturas, patas acertadas/falladas) y lo pasa al bot
rem  2) sube a la nube las lineas de Betano aprendidas (no tus apuestas: esas quedan solo en esta PC)
rem  3) genera FutBot.apk con los datos de hoy y la instala si el celular esta conectado (depuracion USB activa)
rem La ruta real tiene "U con tilde" y Dart/Gradle fallan con ella: se compila desde la unidad virtual R:.
cd /d "%~dp0"
if not exist R:\ subst R: "%~dp0."
set ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe
set CONECTADO=0
"%ADB%" get-state >nul 2>&1 && set CONECTADO=1
if %CONECTADO%==1 (
  if not exist datos\celular mkdir datos\celular
  "%ADB%" pull /sdcard/Android/data/pe.futbot.futbot/files/futbot_aprendizaje.json datos\celular\futbot_aprendizaje.json >nul 2>&1 && (
    echo Aprendizaje del celular:
    python -P bot.py celular
    git add conocimiento\betano_lineas.json
    git diff --cached --quiet -- conocimiento\betano_lineas.json || (git commit -q -m "Aprendizaje: lineas de Betano vistas en capturas" && git push -q && echo Lineas de Betano subidas a la nube.)
  )
)
python -P bot.py exportar
xcopy /e /y /i publicar\paquete.json app_movil\assets\paquete\ >nul
xcopy /e /y /i publicar\escudos app_movil\assets\paquete\escudos >nul
set JAVA_TOOL_OPTIONS=-Djavax.net.ssl.trustStore=C:/Users/Asus/develop/certificados/cacerts-con-avast -Djavax.net.ssl.trustStorePassword=changeit
pushd R:\app_movil
call C:\Users\Asus\develop\flutter\bin\flutter.bat build apk --release
popd
copy /y R:\app_movil\build\app\outputs\flutter-apk\app-release.apk FutBot.apk
echo.
"%ADB%" get-state >nul 2>&1
if errorlevel 1 (
  echo FutBot.apk lista. No veo el celular: conectalo por USB con la depuracion USB activa y vuelve a abrir este archivo,
  echo o copia FutBot.apk al celular e instalala encima. Tus datos se conservan.
) else (
  "%ADB%" install -r FutBot.apk && echo Listo: FutBot actualizado en el celular. Tus datos se conservan.
)
pause
