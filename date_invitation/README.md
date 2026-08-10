# 💌 ¿Quieres salir conmigo?

Una pequeña web romántica hecha con **Flask + HTML + CSS + JavaScript puro**, pensada como
un "asistente" que hace preguntas paso a paso para invitar a alguien a salir.

---

## 1. Estructura del proyecto

```
date_invitation/
│
├── app.py                 # Backend Flask (rutas + envío de correo)
├── requirements.txt        # Dependencias de Python
├── .env.example             # Plantilla de variables de entorno (copiar a .env)
├── static/
│   ├── css/style.css        # Todo el diseño (glassmorphism, animaciones, responsivo)
│   ├── js/script.js         # Flujo de pantallas, botón "No" esquivo, confetti, fetch a /submit
│   ├── images/               # Fotos de los lugares (ver sección 3)
│   └── videos/                # Video de la pantalla 3 (ver sección 4)
│
├── templates/
│      index.html            # Las 5 pantallas + pantalla final, todo en un solo archivo
│
└── README.md
```

---

## 2. Instalación y ejecución

```bash
# 1. Entra a la carpeta del proyecto
cd date_invitation

# 2. (Recomendado) crea un entorno virtual
python3 -m venv venv
source venv/bin/activate      # En Windows: venv\Scripts\activate

# 3. Instala las dependencias
pip install -r requirements.txt

# 4. Copia el archivo de variables de entorno y complétalo (ver sección 5)
cp .env.example .env

# 5. Ejecuta la aplicación
python app.py
```

Abre tu navegador en **http://127.0.0.1:5000**.

> Si no configuras el archivo `.env`, la aplicación sigue funcionando: el flujo llega
> hasta el final y muestra la pantalla de confirmación, pero no se envía ningún correo real
> (verás un aviso en la consola de Flask).

---

## 3. Dónde colocar las imágenes

Reemplaza estos dos archivos por tus propias fotos (mismo nombre, o actualiza la ruta en `index.html`):

```
static/images/cerro-espolon.jpg
static/images/cueva-tecolote.jpg
```

Recomendación: fotos horizontales, mínimo 800x500px, formato `.jpg` o `.webp` para que
carguen rápido. Actualmente esos archivos son imágenes de ejemplo (placeholders) generadas
automáticamente — solo tienes que sobrescribirlas.

---

## 4. Dónde colocar el video

El video de la Pantalla 3 (la de "¿Cómo prefieres vivir la experiencia?") se carga desde:

```
static/videos/preview.mp4
```

Simplemente reemplaza ese archivo por el tuyo (debe conservar el nombre `preview.mp4`,
o si prefieres otro nombre, actualiza el `src` dentro de `templates/index.html` en la
etiqueta `<source>`).

El video ya está configurado para:

* Reproducirse automáticamente (`autoplay`)
* Repetirse en bucle (`loop`)
* Sin sonido (`muted`) — requisito de los navegadores para poder autoreproducir

Recomendación: video corto (5-15 segundos), en formato `.mp4` (códec H.264), para que
el "loop" se sienta fluido y el archivo no pese demasiado.

---

## 5. Configurar el envío de correo (SMTP)

El correo se envía usando `smtplib` de Python con las credenciales guardadas en `.env`
(nunca en el código). Copia `.env.example` a `.env` y completa:

```env
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=tu_correo@gmail.com
SMTP_PASSWORD=tu_contraseña_de_aplicacion
DESTINATION_EMAIL=destinatario@gmail.com
```

### Si usas Gmail:

1. Activa la verificación en dos pasos en tu cuenta de Google.
2. Genera una **"contraseña de aplicación"** en:
   `Cuenta de Google → Seguridad → Verificación en dos pasos → Contraseñas de aplicaciones`.
3. Usa esa contraseña de 16 caracteres en `SMTP_PASSWORD` (no tu contraseña normal).

### Si usas otro proveedor (Outlook, Yahoo, tu propio servidor, etc.):

Solo cambia `SMTP_SERVER` y `SMTP_PORT` por los datos de tu proveedor. El resto del código
no necesita modificarse.

---

## 6. Flujo de la aplicación

1. **Pantalla 1** — "¿Quieres salir conmigo?" con botón "Sí" y un botón "No" que huye del
   cursor y nunca puede presionarse.
2. **Pantalla 2** — Elegir el lugar (dos tarjetas con foto, nombre y descripción).
3. **Pantalla 3** — Elegir cómo vivir la experiencia (llegar directo / acampar / hotel),
   con un video de ejemplo al lado.
4. **Pantalla 4** — Elegir la fecha con un input tipo `date` estilizado.
5. **Pantalla 5** — Resumen de todo lo elegido + botón "Enviar respuesta", que dispara
   confetti y manda el correo vía `/submit`.
6. **Pantalla final** — Mensaje de agradecimiento.

Todo el flujo ocurre sin recargar la página: `script.js` cambia de pantalla animando
opacidad/transformación y guarda las respuestas en un objeto `state` de JavaScript, que
se envía al backend solo hasta el paso final.

---

## 7. Personalización rápida

* **Colores / tipografía**: variables CSS al inicio de `static/css/style.css` (bloque `:root`).
* **Textos**: directamente en `templates/index.html`.
* **Opciones de lugar/experiencia**: agrega o quita tarjetas en `index.html` (bloques
  `.option-card` y `.mini-card`) — el JS ya detecta automáticamente cualquier tarjeta nueva
  gracias a `data-value`.
* **Corazones de fondo**: cantidad y velocidad configurables en `script.js`
  (`HEART_COUNT`, `duration`, `setInterval`).

¡Listo! Con `python app.py` la aplicación queda corriendo y lista para usarse. 💗
