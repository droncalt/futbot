@echo off
rem Genera FutBot.apk (nueva version de la app del celular) con los datos de hoy incluidos.
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
echo Listo: FutBot.apk actualizado. Copialo al celular e instalalo encima (tus datos se conservan).
pause
