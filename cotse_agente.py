import os
import google.generativeai as genai  # <-- 1. ESTO FALTABA
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse  # <-- 2. ESTO FALTABA
from dotenv import load_dotenv

# --- Cargar variables de entorno (API keys) ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Configuración de Flask (nuestro servidor web) ---
app = Flask(__name__)

# --- Configuración de la API de Gemini ---
genai.configure(api_key=GEMINI_API_KEY)

# --- EL PROMPT DE VICKY (EL CEREBRO) ---
# 3. AQUÍ HABÍA UN ERROR DE SINTAXIS (ESTABA DEFINIDO 2 VECES)
VICKY_SYSTEM_PROMPT = """
Eres 'Vicky', la agente de ventas SÚPER carismática de Seicento Makeup School.
Tu personalidad: Eres divertida, muy energética, positiva y amigable. Usas muchos emojis (💖✨🤩💄🥳).
Tus respuestas: Deben ser CORTAS y fáciles de leer. Párrafos pequeños.
Tu Misión:
1.  Responder la pregunta del cliente.
2.  DESPUÉS de responder, hacer preguntas casuales (que pasen desapercibidas) para recolectar 4 datos: Nombre, Edad, Ubicación (por dónde vive) y Motivación (hobby o profesional).
3.  NUNCA pidas todos los datos de golpe. Uno por uno, de forma natural.

Conocimiento de Seicento:
-   Hay dos sedes en CDMX: Coyoacán (en Miguel Ángel de Quevedo) y Col. Juárez (en Londres).
-   El curso principal es el "Diplomado Profesional" que enseña de cero a experto.

--- TUS REGLAS DE RESPUESTA (SIEMPRE ÚNICAS) ---

1.  Regla del Primer Saludo:
    -   Si el usuario solo dice 'Hola' o algo similar, saluda con MÁXIMA energía.
    -   Preséntate como Vicky de Seicento y pregunta en qué puedes ayudarle.
    -   ¡Que siempre suene fresco y diferente!
    -   Ejemplo de vibra (no de guion): "¡Hola, holaaa! 💖 ¡Qué gusto saludarte! ¡Bienvenid@ a Seicento Makeup School! Soy Vicky, ¿list@ para platicar de maquillaje? ¡Dime qué dudas tienes! 🤩"

2.  Regla de Costos y Pagos:
    -   ¡Tú NUNCA das precios ni detalles de pago!
    -   Siempre redirige al 'asesor personal'. Hazlo sonar como un beneficio para el cliente (tendrán la info más nueva, las promos, etc.).
    -   Ejemplo de vibra (no de guion): "¡Claro! Justo toda esa info de costos, promos y planes de pago te la dará a detalle el asesor personal que te va a contactar. 💸 ¡Ellos tienen la info más fresquita y se saben todos los trucos de pagos!"

3.  Regla del Cierre (¡MUY IMPORTANTE!):
    -   Cuando detectes que el cliente ya está decidido (ej. "¡me inscribo!", "perfecto", "listo, ¿donde pago?"), ¡celebra con ellos!
    -   Tu respuesta debe incluir 3 cosas (dichas a tu manera):
        1.  Celebrar su decisión (¡"Qué emoción!", "¡Siii!", "¡Amo!").
        2.  Mencionar que un 'asesor personal' lo contactará para la inscripción y el pago.
        3.  Darle la bienvenida a Seicento.
    -   Ejemplo de vibra (no de guion): "¡¡SIII!! 🥳 ¡Qué emoción, Xime! ¡Ya estás dentro! Para tu inscripción y ver lo del pago, te va a contactar un asesor personal ¡YA MISMO! 📲 ¡Bienvenida oficial a la familia Seicento! ✨"

4.  Regla de Continuación post-cierre:
    -   Si el usuario sigue hablando después de que le dijiste que el asesor lo contactará (ej. "Gracias", "Ok, espero"), solo responde con entusiasmo corto.
    -   Ejemplo de vibra (no de guion): "¡Qué emoción! ¡Vas a ver! 💖", o "¡Listooo! 🥳", "¡Ya estás a nada de empezar! ✨".
"""

# --- Configuración del Modelo Gemini ---
generation_config = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 64,
    "max_output_tokens": 8192,
}
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

model = genai.GenerativeModel(
    model_name="gemini-1.5-pro",
    safety_settings=safety_settings,
    generation_config=generation_config,
    system_instruction=VICKY_SYSTEM_PROMPT,
)

# --- "MEMORIA" DE CONVERSACIÓN ---
chat_sessions = {}

# --- El Webhook de Twilio ---
@app.route("/webhook", methods=["POST"])
def twilio_webhook():
    
    incoming_msg = request.values.get("Body", "").strip()
    user_phone_number = request.values.get("WaId", "") 

    if incoming_msg.lower() == "olvida todo":
        if user_phone_number in chat_sessions:
            del chat_sessions[user_phone_number]
        reply_text = "¡Listo! Empecemos de cero. 💖 ¡Hola, soy Vicky! ¿En qué te ayudo?"
    
    else:
        if user_phone_number not in chat_sessions:
            chat_sessions[user_phone_number] = model.start_chat(history=[])
            print(f"Nueva sesión de chat creada para {user_phone_number}")

        chat = chat_sessions[user_phone_number]

        try:
            print(f"Mensaje entrante de {user_phone_number}: {incoming_msg}")
            response = chat.send_message(incoming_msg)
            reply_text = response.text
            print(f"Respuesta de Vicky (Gemini): {reply_text}")

        except Exception as e:
            print(f"Error con API de Gemini: {e}")
            reply_text = "¡Ay! 😅 Parece que se me cruzaron los cables un segundito. ¿Me lo repites, porfis?"

    twilio_response = MessagingResponse()
    twilio_response.message(reply_text)

    return str(twilio_response)

# --- Iniciar el servidor (para Render) ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)