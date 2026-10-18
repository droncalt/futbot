# ⚽ FútBot — analista de fútbol para Betano

Chat que da fijas y combinadas con probabilidad real, verifica las "fijas" del grupo o de tipsters,
arma la boleta con el formato de Betano y mide con el tiempo quién acierta de verdad.

## Abrir la app
Doble clic en **`iniciar_bot.bat`** → se abre **FútBot** en el navegador: http://localhost:8501
(para apagarlo, cierra la ventana negra). Los datos se actualizan solos cada 6 h al abrirla.
La versión anterior sigue disponible con `python -m streamlit run app.py`.

Para verla desde el celular en la misma red WiFi, edita `iniciar_bot.bat` y agrega
`--server.address 0.0.0.0` al final de la línea de `streamlit`. Luego entra a `http://<IP de tu PC>:8501`.
Windows puede pedir permiso en el firewall.

## Secciones
- **💬 Chat**: escribe *«dame las fijas de mañana»*, *«combinada de 4 con cuota 3 con 20 soles»*, *«más segura»*,
  *«bet builder del Arsenal»*, *«revisa: Leeds o empate a 1.40»*, *«¿qué es el Pago Anticipado?»*.
- **🎯 Fijas**: lo mismo con botones (día, nivel de riesgo, n.º de selecciones, cuota objetivo, monto).
- **📅 Partidos**: tarjetas de cada partido; «Analizar» abre todos los mercados, Bet Builders, ficha y jugadores.
- **🔍 Verificar**: carga fijas con su cuota de Betano (también de Champions con las cuotas 1X2).
- **🧾 Mi boleta**: boleta para copiar, montos rápidos, Multi Bono / Seguro Betano, registrar o «solo seguimiento».
- **📒 Historial**: balance y **¿A quién creerle?** (acierto real del bot, Telegram y cada tipster).
- **📹 Tipsters**: sube el video de un tipster → transcripción → su fija → comparación con el bot → seguimiento.
  También puedes dejar los videos en la carpeta `videos_tipsters/`.
- **📊 Calidad** (backtest) y **📘 Guía** (cómo se usa, cómo funciona, reglas oficiales de Betano, juego responsable).

## Rutina recomendada
1. Abre la app (se actualiza sola) y pide tus fijas en el chat o en **🎯 Fijas**.
2. Agrégalas a **🧾 Mi boleta**, cambia las cuotas «≈» por las reales de Betano y elige el monto.
3. Si la cuota de Betano es menor que la **cuota justa**, esa selección no conviene.
4. Registra lo que juegas y anota como «solo seguimiento» las fijas del grupo/tipsters que no juegas.

## Informe completo de un partido (A–J)
En Claude Code, dentro de esta carpeta, escribe por ejemplo: *"analiza Barcelona vs Getafe"*.
Claude corre el modelo, investiga lesiones, alineaciones y árbitro en fuentes verificables y deja el informe
en `informes/`.

## Línea de comandos
```
python -P bot.py actualizar
python -P bot.py proximos --liga SP1
python -P bot.py analizar --liga SP1 --local Barcelona --visitante Getafe
python -P bot.py analizar --liga OTRA --local Inter --visitante "Club Brugge" --cuotas 1.30,5.5,9.0 --ou 1.65,2.20
python -P bot.py backtest
```

## Tiros al arco de jugadores («Erling Haaland Tiros al Arco 1+»)
Para Premier League, LaLiga, Serie A, Bundesliga y Ligue 1. En **📅 Partidos** (Analizar → pestaña 🎯 Jugadores),
en **🔍 Verificar** (mercado «Jugador - Tiros al Arco», también para Champions buscando al jugador) y su calibración
en **📊 Calidad**. Líneas 1+, 2+ y 3+ (las que tienen backtest). Depende de la alineación: en Betano, con
«Anular jugadores no titulares» (activo por defecto), si el jugador no es titular su selección se anula; por eso el
bot usa por defecto el escenario «Titular».

Datos de jugadores:
- **API-Football** (opcional): crea tu clave gratuita en https://dashboard.api-football.com, copia
  `.env.ejemplo` como **`.env`** y pega la clave después de `APIFOOTBALL_KEY=`. **`.env` es privado**:
  no lo compartas ni pegues la clave en ningún chat. Revisa tu plan con `python -P bot.py jugadores --plan`.
  El plan gratuito da 100 consultas al día y, según su web, solo temporadas antiguas.
- **Understat** (gratis, sin clave): se usa cuando el plan de API-Football no cubre las temporadas recientes.

```
python -P bot.py jugadores --descargar
python -P bot.py backtest-jugadores
python -P pruebas/prueba_app.py          # prueba automática de la app (base SQLite temporal)
python -P bot.py analizar --liga E0 --local "Man City" --visitante Arsenal --jugador Haaland
```

## Importante
- Ningún resultado está garantizado. El bot mide probabilidades; no adivina.
- No usa tu cuenta de Betano ni guarda contraseñas. Las cuotas de Betano las copias tú.
- Más detalles en `docs/como_funciona.md` (también en la pestaña ℹ️ de la app).
