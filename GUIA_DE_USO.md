# 📘 Guía de uso de FútBot

Esta guía explica, paso a paso, cómo encender el bot, qué hace cada pantalla y cómo calcula.
La misma información, más corta, está dentro de la app en la pestaña **📘 Guía**.

---

## 1. Encender el bot

### Forma normal (la que usarás siempre)
1. Abre el Explorador de archivos de Windows.
2. Entra a la carpeta **Documentos → BOT APUESTAS FÚTBOL**.
3. Haz **doble clic** en el archivo **`iniciar_bot.bat`**.
4. Se abre una **ventana negra**: no la cierres, es el "motor" del bot.
5. En unos segundos se abre solo tu navegador en **http://localhost:8501** con FútBot.
   Si no se abre, abre Chrome y escribe esa dirección.
6. Si los datos tienen más de 6 horas, se actualizan **solos en segundo plano** (verás un aviso arriba); puedes
   seguir usando la app mientras tanto.
7. El `.bat` también enciende **Ollama** (la IA local). Si abres la ventana de Ollama y ves una lista de "Apps"
   (Claude Code, Codex, etc.), **no elijas nada**: ciérrala. Solo necesita estar encendido (ícono de la llamita junto al reloj).

### Apagarlo
Cierra la **ventana negra**. La pestaña del navegador deja de funcionar hasta que vuelvas a encenderlo.

### Si algo falla al encender
| Problema | Solución |
|---|---|
| La ventana negra dice «python no se reconoce» | Python no está en el PATH. Avísale a Claude en esta carpeta. |
| El navegador dice «no se puede acceder» | Espera 10 s y recarga (F5). La ventana negra debe seguir abierta. |
| Dice que el puerto 8501 está ocupado | Ya tienes otro FútBot abierto: usa esa pestaña, o cierra todas las ventanas negras y vuelve a abrirlo. |
| «No se pudo actualizar» | No hay internet. El bot sigue funcionando con los datos guardados. |

### 📱 Usarlo en el celular
FútBot corre en tu PC (ahí están los datos, el modelo y la IA); el celular lo abre por el navegador.
1. En la PC, ve a **📘 Guía → 📱 Celular** y **crea un PIN** (el celular te lo pedirá; en la PC no).
2. **En la WiFi de tu casa:** escanea con la cámara del celular el **código QR** que aparece ahí
   (dirección tipo `http://192.168.1.92:8501`). La primera vez Windows preguntará si Python puede usar la red:
   elige **Redes privadas → Permitir**.
3. **Fuera de casa (datos móviles):** instala **Tailscale** (gratis) en la PC y en el celular e inicia sesión con la
   misma cuenta en ambos. Vuelve a 📘 Guía → 📱 Celular: aparecerá otro QR con la dirección privada. Solo tus
   dispositivos pueden entrar.
4. **Instalarlo como app:** Android (Chrome) → menú ⋮ → **Agregar a la pantalla principal / Instalar app**.
   iPhone (Safari) → Compartir → **Agregar a inicio**. Queda el ícono de FútBot como una app.
5. La PC debe estar encendida con FútBot abierto para que funcione en el celular.

### 🧠 La IA local (conversar libremente)
- Corre **en tu PC** con Ollama y el modelo **Qwen3 4B Instruct**: no gasta tokens de Claude, no paga ninguna API.
- Usa **internet** para noticias (Google News: lesiones, bajas, previas, tendencias) y para actualizar datos;
  conversa sin internet con lo que ya tiene.
- Tarda unos 30–60 s por respuesta (tu PC no tiene tarjeta gráfica); verás el texto escribirse en vivo.
- Lo que tú le dices de forma estable ("recuerda que mi monto es 20 soles") lo **guarda** y lo usa siempre.
- Configuración, cambio de modelo y memoria: **📘 Guía → 🧠 IA local**. Si la apagas, el chat usa el modo básico.

---

## 2. Las pantallas (menú de arriba)

En pantallas angostas, como un celular, el menú se esconde en el botón **»** de arriba a la izquierda.

### 💬 Chat (pantalla de inicio)
Le escribes como a una persona. Ejemplos de lo que entiende:

| Quieres… | Escribe |
|---|---|
| Fijas de un día | «dame las fijas de hoy», «fijas de mañana», «fijas del fin de semana», «fijas del domingo» |
| Una combinada a medida | «combinada de 4 con cuota 3 con 20 soles», «triple para mañana», «quiero cuota 2 lo más seguro» |
| Ajustar la última | «más segura», «más cuota», «con 50», «solo goles», «de la Premier», «con córners» |
| Analizar un partido | «cómo ves el Leeds vs United», «bet builder del Arsenal» |
| Revisar una fija del grupo | «revisa: Leeds o empate a 1.40», «Leeds anota a 1.30», «más de 1.5 Osasuna vs Santander @1.15» |
| Reglas de Betano | «¿qué es el Pago Anticipado?», «¿cómo cuentan las tarjetas?», «¿qué pasa si se suspende?», «multi bono» |
| Tu balance | «¿cómo voy con mis apuestas?» |
| Guardar | «agrégala a mi boleta» (guarda la última combinada) |

**Cómo leer la respuesta:**
- **Boleta blanca:** igual a la de Betano. Cada línea tiene la selección (en negrita), el mercado, los equipos, la cuota y la hora (Perú).
- **Cuota con «≈»:** estimada. El bot no puede leer las cuotas de Betano, así que antes de apostar **cópialas de la app de Betano**.
- **Etiqueta «84% prob.»:** probabilidad del bot para esa selección.
- **Ganancias potenciales:** monto × cuota total.
- **Prob. de acertar todo:** la de la boleta completa, más importante que la de cada línea. «Falla ≈ 4 de 10» significa que de cada 10 boletas así se caen unas 4.
- **«¿Por qué…?»:** al abrirlo ves los goles esperados, cuántas veces se cumplió en los últimos partidos, la probabilidad del modelo y del mercado, y qué pasó en el pasado cuando el bot dio una probabilidad parecida.
- **⚡ Pago Anticipado:** si Betano lo activa en ese partido, la probabilidad de cobrar sube (te dice cuánto).
- **🎁:** si la boleta califica (o no) para Multi Bono o Seguro Betano, y por qué.
- **➕ Agregar a mi boleta:** la manda a «Mi boleta» para editarla y registrarla.

El chat no es una inteligencia artificial conversacional: reconoce frases. Si no entiende, te sugiere ejemplos.

### 🎯 Súper boleta (la principal)
Un **Bet Builder por partido** con lo más probable (Menos/Más goles, doble oportunidad, "equipo anota", córners,
tiros al arco 1+ de jugadores titulares), como en tus capturas de Betano.
- **Seguridad de cada línea:** 🛡️ Ultra (~1.15 por línea) · ✅ Segura (~1.25) · ⚖️ Equilibrada (~1.40).
- **Líneas marcadas:** Auto (4) o 2–10, o activa **Cuota objetivo** (ej. 3) y marca las necesarias.
- **Patas por partido:** 1, 2 o 3.
- En la boleta, **todo se actualiza al instante** (sin pedírselo a nadie):
  casilla grande = incluir/quitar el partido · casillas chicas = quitar una pata del Bet Builder ·
  cuota = escribe la real de Betano · monto = escríbelo o +5/+10/+20/+50.
- Debajo de las marcadas hay **más opciones** (en gris) para sumar cuota.
- Muestra **Prob. de acertar todo** y «de cada 10 boletas así, ≈ X se caen», además del Multi Bono si aplica.
- Botones: **➕ A mi boleta**, **✅ La aposté**, **👁️ Solo seguimiento**, **📋 Copiar texto**.

### 📅 Partidos
Tarjetas de cada partido, por día, con:
- la barra de probabilidad local / empate / visitante;
- la selección estrella ⭐;
- la probabilidad de «Más 1.5» y «Ambos anotan»;
- los goles esperados.

Botón **📊 Analizar** → ficha completa con 4 pestañas:
- **Todos los mercados:** tabla con la probabilidad del bot, del modelo y del mercado, la cuota justa, desde qué cuota de Betano conviene y el historial del bot. Marca ➕ y pulsa «Agregar las marcadas». Si marcas varias del mismo partido, quedan como **Bet Builder**.
- **Bet Builders:** combinaciones de 2 mercados del mismo partido con su probabilidad conjunta.
- **Equipos:** forma de la temporada (local/visitante, goles, xG, córners, tarjetas), últimos 8 partidos y enfrentamientos directos.
- **Jugadores:** tiros al arco (1+, 2+…) de cada jugador, para las 5 grandes ligas.

Al final, «Analizar otro partido» sirve para Brasil, Argentina, MLS, México y otras ligas con datos.

### 🔍 Verificar
Para revisar las fijas del grupo de Telegram, de un tipster o tuyas:
1. Elige la competición y los equipos. Para Champions, copas o selecciones elige «Otra competición» y escribe los nombres.
2. Elige el mercado, la opción y la línea.
3. Solo en «Otra competición»: copia de Betano las cuotas **1, X, 2** y **Más/Menos 2.5**. Son obligatorias.
4. Elige de dónde viene (Bot / Propia / Telegram / Tipster con su nombre) y pulsa «Agregar».
5. Escribe la **cuota de Betano** en cada línea. El bot muestra:
   - **Prob. del bot** y **Prob. que paga Betano** (1 ÷ cuota);
   - **Cuota justa** (1 ÷ prob. del bot);
   - **Valor esperado:** positivo = Betano paga más de lo justo;
   - **Veredicto:** 🟢 con valor / 🟡 justa / 🔴 mal pagada;
   - la **línea más débil**, que es la que más riesgo agrega a la combinada.

### 🧾 Mi boleta
- La boleta lista para copiar en Betano. Cambia el **monto** (o usa los montos rápidos 5/10/20/50/100).
- En «Editar cuotas y líneas», escribe las **cuotas reales de Betano**: todo se recalcula. Puedes quitar líneas con 🗑️.
- «📋 Texto para copiar» sirve para WhatsApp o tus notas.
- **✅ La aposté:** la registra con dinero. **👁️ Solo seguimiento:** la registra sin dinero (úsalo para las fijas del grupo que no juegas).
- Las boletas se liquidan solas cuando llegan los resultados. Champions y otras competiciones sin datos se marcan a mano en Historial.

### 📒 Historial
- **Apostado, neto y ROI** de las boletas con dinero.
- **🏆 ¿A quién creerle?:** acierto real de cada fuente (bot, propias, Telegram, cada tipster) comparado con lo que el bot esperaba. Con 50 o más selecciones ya dice algo; con pocas manda la suerte.
- **Calibración:** si tus selecciones de «80 %» se cumplen de verdad 8 de cada 10 veces.
- **Balance acumulado** en gráfico, y opción para marcar resultados a mano (cash out, anuladas) o borrar boletas.

### 📹 Tipsters
1. Descarga el reel o TikTok del tipster.
2. Súbelo con «Video», o déjalo en la carpeta **`videos_tipsters`**, y escribe el nombre del tipster (ej. `lasfijas.latam`).
3. El bot:
   - transcribe lo que dice, en tu PC y sin enviar nada a internet;
   - muestra los fotogramas;
   - detecta su fija («mi opción…») y calcula su propia probabilidad.
4. **📌 Anotar a su nombre:** queda en seguimiento y se mide sola. **➕ A mi boleta:** si la quieres jugar.

La primera vez descarga el modelo de voz (unos 480 MB, una sola vez).

### 📊 Calidad
La prueba honesta del bot: la temporada 2025/26, semana a semana, usando solo los datos que existían antes de cada partido.
- **Fijas del bot ≥ 75 %:** cuánto dijo y cuánto acertó de verdad.
- **Gráfico de calibración:** si los puntos están sobre la línea gris, el bot dice la verdad sobre sus probabilidades.
- **Laboratorio de combinadas:** qué habría pasado jugando favoritos a cuota baja en combinadas.
- Botón para volver a correr la prueba (unos minutos).

### 📘 Guía
- **Cómo se usa** y **cómo funciona**.
- **Reglas de Betano** con buscador y enlace a la página oficial de cada regla.
- **Juego responsable.**

### Barra lateral (botón **»** arriba a la izquierda)
- **Monto por defecto:** el que usa el chat si no dices otro.
- Cuántas líneas tiene tu boleta.
- Fecha de los datos y botón **🔄 Actualizar ahora**.

---

## 3. Cómo calcula (en simple)

1. **Datos:** resultados, xG, remates, córners, tarjetas y cuotas de 31 ligas (football-data.co.uk). Se guardan en `datos/` con fecha y nunca se borra una versión anterior.
2. **Modelo propio:** estima el ataque y la defensa de cada equipo con 3 temporadas (lo reciente pesa más) y calcula la probabilidad de cada marcador: 0-0, 1-0, 2-1… De ahí salen todos los mercados.
3. **Mercado:** las cuotas de varias casas, sin su comisión, dicen lo que «sabe» el mercado (incluye lesiones y noticias que el modelo no ve).
4. **Mezcla:** 20 % modelo + 80 % mercado. No es un número inventado: es el que mejor funcionó en la prueba de la temporada pasada.
5. **Calibración:** si en el pasado, cuando el bot dijo 80 %, pasó 78 %, ajusta hacia 78 %.
6. **Bet Builder:** las patas del mismo partido se calculan juntas («gana Barcelona» y «Más de 2.5» van de la mano), no se multiplican como si fueran independientes.
7. **Combinadas:** un partido por línea, para no repetir riesgo. La probabilidad total es el producto de las líneas.

**Qué significa que "aprende":**
- Cada actualización mete los resultados nuevos y vuelve a estimar el modelo.
- Cada boleta registrada mide el acierto real del bot, del grupo y de cada tipster.

No aprende viendo redes sociales por su cuenta.

---

## 4. Reglas de oro

- **No existe la fija segura.** 3 selecciones de 85 % aciertan juntas solo el 61 % de las veces. 5 aciertan el 44 %.
- **Compara siempre con la cuota justa:** si Betano paga menos, a la larga pierdes aunque aciertes seguido.
- **Cuotas «≈»:** cópialas de Betano antes de decidir.
- **Revisa las noticias:** si el bot avisa que «modelo y mercado discrepan», casi siempre hay una baja o una rotación.
- **Monto fijo y pequeño**, sin subirlo para recuperar pérdidas. Betano tiene límites de depósito y de sesión en tu cuenta.

---

## 5. Extras

- **`actualizar_datos.bat`:** actualiza datos y modelos sin abrir la app.
- **Informe profesional de un partido:** abre Claude Code en esta carpeta y escribe «analiza Barcelona vs Getafe». Claude revisa lesiones, alineaciones y árbitro en fuentes oficiales y deja el informe en `informes/`.
- **Versión anterior de la app:** `python -m streamlit run app.py`.
- **Archivos importantes:**
  - `datos/registro.sqlite`: tu historial. No lo borres.
  - `videos_tipsters/`: videos para procesar.
  - `.env`: clave privada de API-Football, si la configuras. No la compartas.
