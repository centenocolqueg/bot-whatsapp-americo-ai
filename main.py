import logging
from collections import defaultdict, deque

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from groq import AsyncGroq

from config import (
    GROQ_API_KEY,
    VERIFY_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_TOKEN,
)

app = FastAPI(title="Bot WhatsApp AMERICO AI")
groq = AsyncGroq(api_key=GROQ_API_KEY)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

historiales = defaultdict(lambda: deque(maxlen=12))

PROMPT_SISTEMA = """
Eres CENTENO AI, un asistente inteligente creado por AMERICO AI,
bajo la dirección de su CEO Guido Americo Centeno Colque.

Responde de manera clara, profesional, amable y útil.
Puedes ayudar con programación, negocios, estudios, publicidad,
ideas, explicaciones y conversación general.
No menciones proveedores externos, modelos ni claves privadas.
Responde en el idioma utilizado por el usuario.
"""


@app.get("/")
async def inicio():
    return {
        "estado": "activo",
        "servicio": "Bot de WhatsApp AMERICO AI",
    }


@app.get("/webhook", response_class=PlainTextResponse)
async def verificar_webhook(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return hub_challenge

    raise HTTPException(status_code=403, detail="Token de verificación incorrecto")


@app.post("/webhook")
async def recibir_webhook(request: Request, background_tasks: BackgroundTasks):
    datos = await request.json()

    try:
        cambios = datos["entry"][0]["changes"][0]["value"]
        mensajes = cambios.get("messages", [])

        if not mensajes:
            return {"status": "ok"}

        mensaje = mensajes[0]
        numero_usuario = mensaje["from"]
        tipo = mensaje.get("type")

        if tipo == "text":
            texto = mensaje["text"]["body"].strip()
            background_tasks.add_task(
                procesar_mensaje,
                numero_usuario,
                texto,
            )
        else:
            background_tasks.add_task(
                enviar_whatsapp,
                numero_usuario,
                "Por ahora puedo responder mensajes de texto. "
                "Pronto también procesaré audios, imágenes y documentos.",
            )

    except (KeyError, IndexError, TypeError):
        logger.info("Evento recibido sin mensaje procesable")

    return {"status": "ok"}


async def procesar_mensaje(numero_usuario: str, texto: str):
    try:
        historial = historiales[numero_usuario]
        historial.append({"role": "user", "content": texto})

        mensajes_groq = [
            {"role": "system", "content": PROMPT_SISTEMA},
            *list(historial),
        ]

        respuesta = await groq.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=mensajes_groq,
            temperature=0.7,
            max_tokens=1000,
        )

        texto_respuesta = respuesta.choices[0].message.content
        historial.append(
            {"role": "assistant", "content": texto_respuesta}
        )

        await enviar_whatsapp(numero_usuario, texto_respuesta)

    except Exception:
        logger.exception("Error procesando el mensaje")
        await enviar_whatsapp(
            numero_usuario,
            "Disculpa, ocurrió un error temporal. Inténtalo nuevamente.",
        )


async def enviar_whatsapp(numero_destino: str, mensaje: str):
    url = (
        f"https://graph.facebook.com/v23.0/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    encabezados = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    contenido = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": numero_destino,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": mensaje[:4096],
        },
    }

    async with httpx.AsyncClient(timeout=30) as cliente:
        respuesta = await cliente.post(
            url,
            headers=encabezados,
            json=contenido,
        )
        respuesta.raise_for_status()
