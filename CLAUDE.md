# Bot analítico de fútbol (uso personal)

Herramienta de análisis estadístico de partidos para apostar en Betano con información honesta.
No es un generador de apuestas "seguras": mide probabilidades y su calibración.

## Cómo se usa

- App web local **FútBot**: `iniciar_bot.bat` (o `python -m streamlit run futbot.py`), http://localhost:8501.
  Interfaz en `ui/` (estilos, comun, bloques, paginas); `app.py` es la versión clásica anterior.
- Actualizar datos + modelos + liquidar boletas: `actualizar_datos.bat` (o `python -P bot.py actualizar`)
- Informe A–J de un partido: pedir "analiza <local> vs <visitante>" → skill `analisis-partido`
- CLI: `python -P bot.py {actualizar|backtest|equipos|proximos|analizar}` (ver docstring de `bot.py`)

## Estructura

- `motor/config.py` ligas, rutas y parámetros (con la evidencia que justificó cada valor)
- `motor/datos.py` descarga de football-data.co.uk con copias versionadas en `datos/raw/` y registro de consultas
- `motor/modelo.py` Dixon-Coles con decaimiento temporal + xG; córners/tarjetas binomial negativa
- `motor/mercados.py` mercados con nombres de Betano, probabilidades conjuntas (Bet Builder), modelo de mercado
- `motor/analisis.py` verificador de fijas y boleta; `motor/registro.py` SQLite de boletas y calibración
- `motor/evaluacion.py` backtest walk-forward (sin fuga de información) → `datos/evaluacion/resumen.json`

- `motor/jugadores.py` datos de jugadores por partido: API-Football (clave en `.env`, cuota diaria) o Understat
- `motor/modelo_jugadores.py` tiros al arco por jugador (Gamma-Poisson + defensa rival + escenarios de alineación);
  `motor/evaluacion_jugadores.py` su backtest → `datos/evaluacion/resumen_jugadores.json`
- `.env` es PRIVADO (APIFOOTBALL_KEY=...): nunca leerlo en voz alta, copiarlo ni pedir la clave por chat

- `motor/fijas.py` generador de fijas/combinadas (calibración del backtest con encogimiento, DP para cuota objetivo)
- `motor/asistente.py` chat por reglas (intenciones en español, alias de equipos); `motor/betano.py` reglas oficiales
  (`conocimiento/betano_reglas.json`, fuente support.betano.pe), Multi Bono, Seguro, Pago Anticipado, cuotas estimadas
- `motor/videos.py` videos de tipsters: faster-whisper local (audio vía FFmpeg; `av` 19 rompe su decodificador),
  detección de «mi opción…», registro como `tipster:<nombre>` solo seguimiento
- Cuotas de Betfair Exchange pueden ser basura (1.01 sin liquidez): `datos.cuotas_sanas/cuotas_coherentes` las filtran
- Tarjetas según Betano: amarilla 1, roja 2 (`modelo.puntos_tarjetas`)
- `motor/combinador.py` Súper boleta: por partido, el Bet Builder (≤3 patas) MÁS probable que pague ≥ cuota del nivel
  (ultra 1.15 / segura 1.25 / equilibrada 1.40); precalcula subconjuntos de patas para la boleta en vivo
- `ui/boleta_vivo.py` componente Streamlit CCv2 (inline): toda la cuenta en JS, sin reruns; solo los botones mandan
  un trigger `accion` (manejado en `ui.comun._accion_boleta`)
- `motor/ia_local.py` IA LOCAL gratuita vía Ollama (`qwen3:4b-instruct`; la variante `qwen3:4b` "piensa" y es lentísima en
  esta PC sin GPU). Prefijo system+tools fijo para reusar la caché; atajos (`_preruta`) a herramientas; respuesta en
  streaming; herramienta `noticias` = Google News RSS. El usuario NO quiere gastar tokens de Claude/API en el bot.
- `ui/acceso.py` acceso móvil: PIN (hash en `datos/acceso.json`) para IPs no locales, QR de la IP WiFi/Tailscale
- `iniciar_bot.bat` abre Ollama y Streamlit en 0.0.0.0:8501
- `motor/equipos.py` nombres completos (tabla COMPLETO + TheSportsDB) y escudos en `datos/escudos/` (TheSportsDB free key 123,
  limita consultas; respaldo Wikipedia pageimages). Enlaces Betano = páginas PÚBLICAS de liga (`BETANO_LIGAS`); Betano no
  permite enlaces que carguen una boleta ni hay códigos de evento sin raspar su sitio (prohibido).
- App Android: `app_movil/` (Flutter). Datos: `bot.py exportar` → `publicar/paquete.json` + escudos; en la nube lo corre
  `.github/workflows/datos_diarios.yml` (GitHub Pages, 6:00 y 18:00 Perú). Compilar con `compilar_apk.bat`: la ruta tiene
  "Ú" y rompe el analizador de Dart y la caché de Kotlin → se usa `subst R:` y `kotlin.incremental=false`; Gradle usa
  `C:\Users\Asus\develop\certificados\cacerts-con-avast`. Nube: repo público droncalt/futbot (gh CLI), Pages
  https://droncalt.github.io/futbot/ (URL por defecto en la app). `actualizar_celular.bat` = compilar + `adb install` +
  traer `futbot_aprendizaje.json` del celular (`bot.py celular`: líneas de Betano → `conocimiento/betano_lineas.json`
  y se suben; patas → `datos/celular/` PRIVADO). Release sin R8 (rompía shared_preferences → pantalla en blanco).
- App: `chat.dart` (pedidos en español → DP máx. prob. para cuota pedida), `vivo.dart` (ESPN público: marcador,
  stats, tiros por jugador; prob. en vivo aprox. Poisson; liquida), `captura.dart` (OCR ML Kit en el celular; tuyas o
  de tipsters; aprende líneas que Betano ofrece). Jugadores: `combinador.linea_min_jugador` (capturas o
  `JUG_ARCO_1_OCULTA`), patas con `alternativas`. `datos/raw/understat` y `datos/jugadores` van en el repo (la nube
  no puede rebajarlos en 45 min).
- `motor/espn.py` calendario + cuotas DraftKings (API pública de ESPN) de hoy a +3 días: Champions/Europa/Conference,
  Libertadores, Sudamericana, Liga 1 Perú y las ligas del bot entre semana (football-data solo trae la jornada). Se suma
  en `datos.cargar_proximos`; sin modelo propio → `combinador._Partido` usa solo el mercado (aviso). Línea de goles ≠ 2.5
  se traduce a Más/Menos 2.5 equivalente (Poisson). Escudos de copas = URL de ESPN.
- Paquete: por partido `mercados` (~143 probabilidades "mercado|opcion|linea"), `esperados` y `jugadores` (top tiros
  al arco). App: `lectura.dart` (3 formatos reales de Betano), `compartir.dart` (boleta como imagen, share_plus),
  `noticias.dart` (Google Noticias RSS: pronósticos y bajas), prueba de OCR por adb: imágenes en
  `/sdcard/Android/data/pe.futbot.futbot/files/prueba_ocr/` → al abrir la app escribe `<imagen>.txt`.

## Reglas del proyecto

- Nunca iniciar sesión en Betano ni guardar credenciales; las cuotas de Betano las ingresa el usuario.
- Nada de scraping de Betano ni de grupos de Telegram. Las fijas del grupo se cargan a mano y se miden.
- Tampoco iniciar sesión ni automatizar Instagram/TikTok: los videos de tipsters los descarga el usuario.
- Cambiar parámetros del modelo solo con backtest que lo justifique; anotar la evidencia en `config.py`.
- Python: ejecutar con `python -P`; HTTPS usa `truststore` (Avast intercepta certificados).
