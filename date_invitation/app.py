"""
app.py
------
Backend Flask para la aplicación romántica "¿Quieres salir conmigo?".

Responsabilidades:
    1. Servir la plantilla principal (index.html) con todo el flujo de pantallas.
    2. Recibir la respuesta final del usuario en la ruta POST /submit.
    3. Enviar un correo electrónico con el resumen del plan usando SMTP.

Las credenciales de correo NUNCA se escriben aquí directamente.
Se cargan desde un archivo .env mediante python-dotenv (ver README.md).
"""

import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuración inicial
# ---------------------------------------------------------------------------

# Carga las variables definidas en el archivo .env al entorno del proceso.
load_dotenv()

app = Flask(__name__)

# Variables de entorno para el envío de correo (definidas en .env)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").strip().lower() in {"1", "true", "yes", "on"}
SMTP_EMAIL = os.getenv("SMTP_EMAIL")            # correo que envía
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip().replace(" ", "")  # contraseña de aplicación
DESTINATION_EMAIL = os.getenv("DESTINATION_EMAIL")  # correo que recibe la invitación aceptada
MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN", "")
MAILGUN_FROM = os.getenv("MAILGUN_FROM", SMTP_EMAIL or "")


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Renderiza la página principal con todo el flujo (SPA de un solo archivo)."""
    return render_template("index.html")


@app.route("/test-email", methods=["GET"])
def test_email():
    """Endpoint de diagnóstico para probar el envío de correo."""
    result = enviar_correo("Prueba", "Prueba", "Prueba")
    return jsonify(result), 200


@app.route("/submit", methods=["POST"])
def submit():
    """
    Recibe la selección final del usuario (lugar, experiencia y fecha)
    y envía un correo electrónico con el resumen del plan.

    Body JSON esperado:
        {
            "lugar": "Cerro del Espolón",
            "experiencia": "Acampar",
            "fecha": "2026-08-20"
        }
    """
    print("[DEBUG] /submit endpoint called")
    print(f"[DEBUG] SMTP_EMAIL: {SMTP_EMAIL}")
    print(f"[DEBUG] DESTINATION_EMAIL: {DESTINATION_EMAIL}")

    data = request.get_json(silent=True) or {}

    lugar = data.get("lugar", "No especificado")
    experiencia = data.get("experiencia", "No especificado")
    fecha = data.get("fecha", "No especificado")

    # Si no hay credenciales configuradas, evitamos que la app truene:
    # devolvemos éxito "simulado" para que el frontend pueda seguir el flujo
    # (útil en desarrollo local sin .env configurado).
    if not SMTP_EMAIL or not SMTP_PASSWORD or not DESTINATION_EMAIL:
        app.logger.warning(
            "Variables SMTP no configuradas. Revisa tu archivo .env. "
            "No se envió ningún correo real."
        )
        print("[DEBUG] Missing SMTP variables")
        return jsonify({
            "status": "ok",
            "email_sent": False,
            "message": "Plan guardado (correo no enviado: configura .env)."
        }), 200

    try:
        result = enviar_correo(lugar, experiencia, fecha)
        return jsonify({
            "status": "ok",
            "email_sent": result["email_sent"],
            "message": result["message"],
            "smtp_error": result.get("smtp_error")
        }), 200
    except Exception as error:
        print(f"[DEBUG] Error: {error}")
        app.logger.error(f"Error enviando correo: {error}")
        return jsonify({
            "status": "ok",
            "email_sent": False,
            "message": "Plan guardado, pero el correo no pudo enviarse.",
            "smtp_error": str(error)
        }), 200


def enviar_correo(lugar, experiencia, fecha):
    """Construye y envía el correo con el resumen del plan vía SMTP o Mailgun."""

    asunto = "Nuevo plan aceptado "

    cuerpo = f"""Nuevo plan aceptado

Lugar:
{lugar}

Experiencia:
{experiencia}

Fecha:
{fecha}
"""

    if MAILGUN_API_KEY and MAILGUN_DOMAIN:
        try:
            response = requests.post(
                f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
                auth=("api", MAILGUN_API_KEY),
                data={
                    "from": MAILGUN_FROM or f"Mailgun Sandbox <postmaster@{MAILGUN_DOMAIN}>",
                    "to": DESTINATION_EMAIL,
                    "subject": asunto,
                    "text": cuerpo,
                },
                timeout=10,
            )
            response.raise_for_status()
            return {
                "email_sent": True,
                "message": "¡Correo enviado con éxito!"
            }
        except requests.exceptions.HTTPError as http_err:
            body = http_err.response.text if getattr(http_err, 'response', None) is not None else ''
            app.logger.error(f"Mailgun HTTP error: {http_err} - {body}")
            return {
                "email_sent": False,
                "message": "Correo no enviado.",
                "smtp_error": str(http_err),
                "mailgun_response": body
            }
        except Exception as error:
            app.logger.error(f"Error enviando correo con Mailgun: {error}")
            return {
                "email_sent": False,
                "message": "Correo no enviado.",
                "smtp_error": str(error)
            }

    mensaje = MIMEMultipart()
    mensaje["From"] = SMTP_EMAIL
    mensaje["To"] = DESTINATION_EMAIL
    mensaje["Subject"] = asunto
    mensaje.attach(MIMEText(cuerpo, "plain", "utf-8"))

    try:
        if SMTP_USE_SSL or SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.sendmail(SMTP_EMAIL, DESTINATION_EMAIL, mensaje.as_string())
        else:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.sendmail(SMTP_EMAIL, DESTINATION_EMAIL, mensaje.as_string())
        return {
            "email_sent": True,
            "message": "¡Correo enviado con éxito!"
        }
    except Exception as error:
        app.logger.error(f"Error enviando correo: {error}")
        print(f"[DEBUG] SMTP error: {error}")
        return {
            "email_sent": False,
            "message": "Correo no enviado.",
            "smtp_error": str(error)
        }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=5000)
