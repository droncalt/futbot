# 📱 FútBot en el celular (sin depender de la PC)

## Cómo funciona
```
GitHub (nube gratis) ──cada día 6:00 y 18:00──▶ calcula súper boletas, partidos y resultados
        │                                          y los publica en tu página de GitHub Pages
        ▼
App FútBot (APK en tu Android) ──al abrirla──▶ descarga el paquete y lo guarda (funciona sin internet)
```
- La PC solo se usa para **instalar versiones nuevas de la app** (APK por cable o WhatsApp).
- El chat con IA y los videos de tipsters siguen en la PC (un modelo de IA no cabe en el celular).

## 1. Instalar la app (ya)
1. Copia al celular el archivo **`FutBot.apk`** de esta carpeta (por cable USB, WhatsApp «a mí mismo» o Google Drive).
2. Ábrelo en el celular. Android pedirá permiso para **instalar apps de origen desconocido**: permítelo solo para esa app.
3. Abre **FútBot**. Ya trae los datos de hoy incluidos, así que funciona desde el primer momento.

## 2. Conectar la nube (una sola vez, ~10 minutos)
Esto hace que los datos se actualicen solos todos los días sin la PC.
1. Crea una cuenta gratis en **github.com** (correo + contraseña; esto lo haces tú).
2. Avísale a Claude en esta carpeta: «ya tengo la cuenta de GitHub». Claude instalará la herramienta de GitHub y te
   pedirá que inicies sesión **tú** en una ventana del navegador (Claude nunca ve tu contraseña). Luego sube el
   proyecto como repositorio **`futbot`**, activa GitHub Pages y lanza el primer cálculo.
3. Tu dirección de datos será: **`https://TU-USUARIO.github.io/futbot/`**
4. En la app: **Ajustes → Dirección de datos** → pega esa dirección → **Guardar y actualizar ahora**.

> Qué se sube a GitHub: el código del bot y los cálculos diarios. **No** se sube tu historial de apuestas, tu PIN,
> la memoria de la IA, tus videos ni claves (están en `.gitignore`). El repositorio debe ser **público** para que
> GitHub Pages sea gratis; nadie puede modificarlo sin tu cuenta.

## 3. Usar la app
- **Boleta**: nivel (Ultra / Segura / Equilibrada), día, n.º de líneas o cuota objetivo. Marca/desmarca líneas y
  patas, escribe la cuota real de Betano y el monto: **todo se recalcula al instante**. Botones: La aposté,
  seguimiento 👁️, copiar 📋 y abrir Betano ↗.
- **Partidos**: probabilidades de cada partido con escudos y enlace a su liga en Betano.
- **Historial**: tus boletas guardadas en el celular; se liquidan solas con los resultados del día.
- **Reglas**: reglas oficiales de Betano con buscador.
- **Ajustes**: dirección de datos y actualización manual.

## 4. Actualizar la app
Cuando haya una versión nueva, Claude genera un `FutBot.apk` nuevo: lo instalas encima y **tus datos se conservan**.

## Por qué no hay "enlace que carga la apuesta en Betano"
Betano no ofrece una forma pública de crear un enlace que cargue una boleta: su botón de compartir solo funciona con
boletas creadas dentro de Betano, y abrir un partido exacto exige sus códigos internos (que solo se obtendrían
raspando su sistema, algo que su reglamento prohíbe). Por eso cada línea trae **«Ver en Betano ↗»**, que abre la
página de esa liga en Betano (en el celular puede abrirse directo en la app de Betano), y el botón **📋 Copiar**.
