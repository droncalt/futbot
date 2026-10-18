## Cómo funciona el bot (y qué NO puede hacer)

### Lo primero: no existe la apuesta segura
Una cuota de **1.20** significa que la casa calcula que eso pasa unas **8 de cada 10 veces**, y además se queda
con un margen. Las 2 que fallan no son "sorpresas": están dentro de la cuota. Si combinas 5 selecciones al 80 %,
la probabilidad de acertar todas es 0,8⁵ ≈ **33 %**. Por eso las combinadas de "fijas" se caen tan seguido.

El bot no promete acertar siempre. Hace algo más útil: **te dice la probabilidad real de cada selección**,
si Betano la está pagando bien o mal, y **lleva la cuenta** para que veas con tus propios números quién acierta.

### De dónde salen los datos
- **football-data.co.uk**: resultados de 31 ligas desde 2012. En las 21 ligas europeas también trae xG,
  remates, tiros al arco, córners, tarjetas, árbitro y cuotas de varias casas (incluida la bolsa Betfair).
- Cada descarga se guarda con fecha en `datos/raw/` y queda anotada en `datos/registro_descargas.csv`.
  Nunca se borra una versión anterior.
- **No** se usa tu cuenta de Betano ni se copia nada de grupos privados.

### Los tres números de cada selección
1. **Modelo**: un modelo Dixon-Coles (estándar en análisis de fútbol). Estima ataque y defensa de cada equipo
   con 3 temporadas de datos. Los partidos recientes pesan más y el xG pesa la mitad cuando existe.
   Con eso calcula la probabilidad de cada marcador, y de ahí todos los mercados.
2. **Mercado**: lo que "piensan" las casas, con su margen quitado. Para Champions, selecciones u otras
   competiciones sin datos, se calcula con las cuotas 1X2 y Más/Menos 2.5 que copies de Betano.
3. **Bot**: la combinación de ambos. El peso de cada uno **no es inventado**: sale del backtest
   (hoy, 20 % modelo y 80 % mercado, porque el mercado resultó más preciso).

### Bet Builder
Las patas de un mismo partido no son independientes ("Barcelona gana" y "Más de 2.5" van de la mano).
El bot calcula su probabilidad **conjunta** sobre la misma distribución de marcadores. No multiplica las patas
como si fueran separadas. Entre goles y córners/tarjetas asume independencia, y lo avisa.

### Cómo se mide si sirve (backtest)
Se simuló la temporada 2025/26 semana a semana: cada lunes el bot solo "sabía" lo ocurrido hasta ese día,
predecía la semana y luego se comparaba con lo que pasó. Resultados en la pestaña **📊 Calidad del modelo**:
- **Calibración**: cuando el bot dice 80 %, ¿pasa 8 de cada 10 veces? (es lo más importante).
- **Contra el mercado**: el modelo solo es *peor* que las casas; combinado es apenas mejor que las cuotas
  de apertura. El mercado al cierre (con alineaciones) sigue siendo el más preciso.
- **Laboratorio de combinadas**: qué habría pasado jugando favoritos a cuota baja en combinadas.

### Qué significa "aprender"
- **Actualizar datos** (botón 🔄): entran los resultados nuevos y **se re-estiman** los parámetros del modelo.
  Eso es actualización, no "inteligencia que aprende sola".
- **Backtest**: vuelve a medir el modelo y re-estima el peso modelo/mercado con evidencia.
- **Tu historial**: cada boleta registrada (apostada o de solo seguimiento) se liquida sola con los resultados
  y mide la calibración real de las selecciones, por fuente (bot, Telegram, propias).
- Los cambios de parámetros del modelo solo se hacen si el backtest los justifica, y queda anotado por qué.

### Tiros al arco de jugadores («Erling Haaland Tiros al Arco 1+»)
Solo Premier League, LaLiga, Serie A, Bundesliga y Ligue 1, con datos por partido de cada jugador
(minutos, tiros y tiros al arco). Fuente: **API-Football** con tu clave privada en `.env`, o **Understat**
(gratis) cuando tu plan de API-Football no incluye las temporadas recientes.
- **Tasa por 90 minutos** del jugador, encogida hacia la media de su posición (un jugador con pocos partidos
  se parece más al promedio; uno con muchos, a sí mismo). Las apariciones recientes pesan más.
- **Defensa rival**: cuántos tiros al arco concede el rival (football-data), y si juega de local o visitante.
- **Minutos**: el modelo **no sabe** si va a ser titular. Muestra escenarios: *titular* (minutos de sus últimas
  titularidades), *juega (titular o suplente)* y *entra desde el banco* (el que entra tira más por minuto).
- **Regla de Betano**: con «Anular jugadores no titulares» (activo por defecto), si tu jugador no sale de titular su
  selección se anula, y en un Bet Builder una selección anulada anula todo el Bet Builder. Por eso el escenario que
  importa es **titular**. Si desactivaste esa opción, mira *juega (titular o suplente)*.
- Betano liquida con datos de Opta, que cuentan como tiro al arco también los bloqueos del último defensor; Understat
  no, así que con esa fuente el bot queda apenas conservador.
- No hay cuotas de mercado de jugadores en datos gratuitos: la probabilidad es **solo del modelo**. Su backtest
  propio está en **📊 Calidad** (sección «Tiros al arco de jugadores»). Solo líneas 1+, 2+ y 3+.

### Lo que el bot todavía no calcula
Goleadores, córners del 1.er tiempo y hándicaps: no hay datos gratuitos fiables.
Para eso, el informe completo (pídeselo a Claude en esta carpeta: "analiza X vs Y") investiga en fuentes
verificables, pero sin inventar probabilidades.

### Lesiones y alineaciones
El modelo **no sabe** quién juega. Por eso, cuando modelo y mercado discrepan mucho, el bot avisa:
casi siempre el mercado ya descontó una baja o una rotación. Revisa las noticias antes de apostar.

### Chat, fijas y tipsters
- **Chat**: entiende pedidos en español con reglas (no es una IA conversacional ni usa internet): fijas por día,
  número de selecciones, cuota objetivo, monto, ligas, «más segura», «más cuota», revisar una fija y reglas de Betano.
- **Fijas**: elige, por partido, la selección con mayor probabilidad **calibrada** (corregida con lo que pasó en el
  backtest) y arma la combinada más probable con un partido por línea. Las cuotas «≈» son estimadas: cópialas de Betano.
- **Reglas de Betano**: resumidas del centro de ayuda oficial de Betano Perú (con enlace y fecha). Ejemplos: Pago
  Anticipado (2 goles de ventaja), Multi Bono (desde triples, cuota ≥ 1.50 por selección), Seguro Betano (5–20
  selecciones a ≥ 1.65), roja = 2 tarjetas, prórroga y penales no cuentan.
- **Tipsters**: el video se transcribe en tu PC, se detecta «mi opción…», el bot calcula su propia probabilidad y la
  fija queda anotada a nombre del tipster. Con 50+ fijas anotadas sabrás si acierta más de lo que el bot esperaba.
