# ============================================================
# NICO OAuth + Gemini 2.0 Flash-Lite + Voz en Navegador
# (con búsqueda en internet / Google Search + saludo único + 
#  voz grave sincronizada con el video)
# ============================================================

import os
import urllib.parse
import json
import base64
import random
import requests
import uuid

import streamlit as st
import streamlit.components.v1 as components

from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
from dotenv import load_dotenv

# ------------------------------------------------------------
# Configuración inicial de Streamlit
# ------------------------------------------------------------
st.set_page_config(
    page_title="NICO | Asistente Virtual UMSNH",
    page_icon="🦊",
    layout="wide",
)

# ------------------------------------------------------------
# FIX redirección /oauth2callback en Streamlit Cloud
# ------------------------------------------------------------
_request_uri = os.environ.get("STREAMLIT_SERVER_REQUEST_URI", "")
if "/oauth2callback" in _request_uri:
    parsed = urllib.parse.urlparse(_request_uri)
    query = urllib.parse.parse_qs(parsed.query)
    st.experimental_set_query_params(**query)
    st.experimental_rerun()

# ------------------------------------------------------------
# Cargar variables de entorno (para desarrollo local)
# ------------------------------------------------------------
load_dotenv()

CLIENT_ID = st.secrets.get("GOOGLE_CLIENT_ID", os.getenv("GOOGLE_CLIENT_ID", ""))
CLIENT_SECRET = st.secrets.get(
    "GOOGLE_CLIENT_SECRET", os.getenv("GOOGLE_CLIENT_SECRET", "")
)
GOOGLE_REDIRECT_URI = st.secrets.get(
    "GOOGLE_REDIRECT_URI",
    os.getenv("GOOGLE_REDIRECT_URI", "https://nicooapp-umsnh.streamlit.app/"),
)

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
GEMINI_MODEL = st.secrets.get(
    "GEMINI_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite-001")
)

# ============================================================
# Funciones auxiliares
# ============================================================


def get_flow(state=None):
    """Crear flujo OAuth con la config embebida (sin archivo JSON)."""
    client_config = {
        "web": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [
                "https://nicooapp-umsnh.streamlit.app/",
                "http://localhost:8501/",
                "http://127.0.0.1:8501/",
            ],
        }
    }

    flow = Flow.from_client_config(
        client_config, scopes=SCOPES, redirect_uri=GOOGLE_REDIRECT_URI
    )
    if state:
        flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow


def ensure_session_defaults():
    """Valores por defecto en session_state."""
    st.session_state.setdefault("logged", False)
    st.session_state.setdefault("profile", {})
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("voice_on", True)
    st.session_state.setdefault("temperature", 0.7)
    st.session_state.setdefault("top_p", 0.9)
    st.session_state.setdefault("max_tokens", 256)
    st.session_state.setdefault("current_video", None)
    st.session_state.setdefault("open_cfg", False)
    # 👇 Para que solo salude una vez por usuario
    st.session_state.setdefault("greeted", False)


def header_html():
    """Cabecera con avatar de video circular."""
    video_path = "assets/videos/nico_header_video.mp4"
    if os.path.exists(video_path):
        with open(video_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        video_tag = f"""
        <img class=\"nico-video\" src=\"assets/img/nico_icon.png\" alt=\"UMSNH\" />
        """
    else:
        video_tag = '<div class="nico-placeholder"></div>'

    return f"""
    <style>
    .nico-header {{
        background:#0f2347;
        color:#fff;
        padding:16px 20px;
        border-radius:8px;
    }}
    .nico-wrap {{
        display:flex;
        align-items:center;
        gap:16px;
    }}
    .nico-video, .nico-placeholder {
        width:56px;
        height:56px;
        border-radius:50%;
        object-fit:cover;
        background:#fff0;
}}
    .nico-title {{
        font-size:26px;
        font-weight:800;
        margin:0;
    }}
    .nico-subtitle {{
        margin:0;
        font-size:18px;
        opacity:.9;
    }}
    .chat-bubble {{
        background:#f8fbff;
        border:2px solid #dfe8f9;
        border-radius:14px;
        padding:18px;
        margin-top:12px;
    }}
    </style>
    <div class="nico-header">
        <div class="nico-wrap">
            {video_tag}
            <div>
                <p class="nico-title">NICO</p>
                <p class="nico-subtitle">Asistente Virtual UMSNH</p>
            </div>
        </div>
    </div>
    """


def login_view():
    """Pantalla de login con botón de Google."""
    st.markdown(header_html(), unsafe_allow_html=True)
    st.info("Inicia sesión con tu cuenta de Google para usar **NICO**.")

    if not CLIENT_ID or not CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
        st.error("Faltan variables de configuración OAuth.")
        return

    if "oauth_state" not in st.session_state:
        st.session_state["oauth_state"] = str(uuid.uuid4())

    state_key = st.session_state["oauth_state"]
    flow = get_flow(state=state_key)

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes=False,
        prompt="consent",
        state=state_key,
    )

    st.experimental_set_query_params(oauth_state=state_key)
    st.markdown(f"[🔐 Iniciar sesión con Google]({auth_url})")


def exchange_code_for_token():
    """Intercambiar el código OAuth por tokens y obtener perfil del usuario."""
    params = st.experimental_get_query_params()
    if "code" not in params or "state" not in params:
        return

    try:
        code = params["code"][0]
        state = params["state"][0]

        if "oauth_state" not in st.session_state:
            st.session_state["oauth_state"] = state

        if state != st.session_state.get("oauth_state"):
            st.warning("⚠️ El estado OAuth se regeneró automáticamente.")
            st.session_state["oauth_state"] = state

        flow = get_flow(state=state)
        flow.fetch_token(code=code)
        creds = flow.credentials

        request = grequests.Request()
        idinfo = id_token.verify_oauth2_token(creds.id_token, request, CLIENT_ID)

        st.session_state["logged"] = True
        st.session_state["profile"] = {
            "email": idinfo.get("email"),
            "name": idinfo.get("name"),
            "picture": idinfo.get("picture"),
        }

        st.experimental_set_query_params()
        st.rerun()

    except Exception as e:
        st.error(f"Error al autenticar: {e}")


# ============================================================
# Gemini 2.0 con búsqueda en internet (Google Search tool)
# ============================================================
def gemini_generate(prompt: str, temperature: float, top_p: float, max_tokens: int) -> str:
    """
    Llamada a Gemini 2.0 Flash-Lite usando la API de Generative Language
    con la herramienta `google_search` habilitada para hacer búsquedas web.
    """
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": float(temperature),
            "topP": float(top_p),
            "maxOutputTokens": int(max_tokens),
        },
        # Habilitamos la herramienta de búsqueda en la web
        "tools": [
            {
                "google_search": {}
            }
        ],
    }

    try:
        r = requests.post(endpoint, headers=headers, json=payload, timeout=40)
        r.raise_for_status()
        data = r.json()

        text = ""
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                text += part.get("text", "")

        return text.strip() or "No obtuve respuesta del modelo."
    except Exception as e:
        return f"⚠️ Error con Gemini: {e}"


def speak_browser(text: str):
    """
    Usa la Web Speech API del navegador para leer el texto
    con voz más grave/masculina en español si está disponible
    y sincroniza el video: play al iniciar, pausa al terminar.
    """
    if not text:
        return

    payload = json.dumps(text)  # escapa comillas, etc.

    js_code = f"""
    <script>
    (function() {{
        const text = {payload};
        const synth = window.speechSynthesis;
        if (!synth) return;

        function speak() {{
            synth.cancel();
            const utter = new SpeechSynthesisUtterance(text);

            const voices = synth.getVoices() || [];
            let chosen = null;

            // Preferir voces masculinas/neutras en español
            const preferNames = ["rocko", "miguel", "diego", "jorge", "pablo", "male", "hombre"];
            for (const v of voices) {{
                const name = (v.name || "").toLowerCase();
                const lang = (v.lang || "").toLowerCase();
                if (lang.startsWith("es")) {{
                    for (const pref of preferNames) {{
                        if (name.includes(pref)) {{
                            chosen = v;
                            break;
                        }}
                    }}
                }}
                if (chosen) break;
            }}

            // Si no hay, cualquier voz en español
            if (!chosen) {{
                for (const v of voices) {{
                    const lang = (v.lang || "").toLowerCase();
                    if (lang.startsWith("es")) {{
                        chosen = v;
                        break;
                    }}
                }}
            }}

            if (chosen) {{
                utter.voice = chosen;
            }}

            // Voz más grave / neutra
            utter.rate = 0.95;   // un poco más lenta
            utter.pitch = 0.65;  // más grave

            // 🔥 Sincronización con el video
            utter.onstart = () => {{
                const v = parent.document.querySelector('video');
                if (v) {{ v.play(); }}
            }};

            utter.onend = () => {{
                const v = parent.document.querySelector('video');
                if (v) {{ v.pause(); }}
            }};

            synth.speak(utter);
        }}

        if (synth.getVoices().length === 0) {{
            synth.addEventListener('voiceschanged', function handler() {{
                synth.removeEventListener('voiceschanged', handler);
                speak();
            }});
        }} else {{
            speak();
        }}
    }})();
    </script>
    """

    components.html(js_code, height=0)


# ============================================================
# Lógica principal de la app
# ============================================================

ensure_session_defaults()
exchange_code_for_token()

if not st.session_state.get("logged"):
    login_view()
    st.stop()

# Cabecera
st.markdown(header_html(), unsafe_allow_html=True)

# Layout: chat + video
conv_col, video_col = st.columns([0.7, 0.3])

with video_col:
    video_container = st.empty()
    if st.session_state["current_video"]:
        video_container.markdown(
            st.session_state["current_video"], unsafe_allow_html=True
        )

with conv_col:
    # Barra superior de controles
    c1, c2, c3 = st.columns([0.1, 0.1, 0.8])

    with c1:
        if st.button(
            "🎙️ Voz: ON" if st.session_state["voice_on"] else "🔇 Voz: OFF"
        ):
            st.session_state["voice_on"] = not st.session_state["voice_on"]

    with c2:
        if st.button("⚙️ Config"):
            st.session_state["open_cfg"] = True

    with c3:
        st.write(f"Bienvenido, **{st.session_state['profile'].get('name', '')}**")

    # Popover de configuración del modelo
    if st.session_state.get("open_cfg"):
        with st.popover("Configuración del Modelo"):
            st.slider(
                "Temperatura", 0.0, 1.5, key="temperature", help="Controla la creatividad"
            )
            st.slider("Top-P", 0.0, 1.0, key="top_p")
            st.slider(
                "Máx. tokens",
                64,
                2048,
                key="max_tokens",
                step=32,
            )
            if st.button("Cerrar"):
                st.session_state["open_cfg"] = False

    st.markdown("### 💬 Conversación")

    # Entrada del usuario
    col_input, col_clear = st.columns([0.8, 0.2])
    with col_input:
        user_msg = st.text_input("Escribe tu pregunta:")
    with col_clear:
        if st.button("🧹 Borrar"):
            user_msg = ""
            st.session_state["_clear_flag"] = True
            st.rerun()

    if st.session_state.get("_clear_flag"):
        user_msg = ""
        st.session_state["_clear_flag"] = False

    if st.button("Enviar") and user_msg.strip():("Escribe tu pregunta:")

    if st.button("Enviar") and user_msg.strip():
        # Guardar mensaje de usuario
        st.session_state["history"].append(
            {"role": "user", "content": user_msg.strip()}
        )

        # Seleccionar y mostrar video aleatorio en la columna derecha
        try:
            video_files = [
                f
                for f in os.listdir("assets/videos")
                if f.lower().endswith((".mp4", ".webm", ".ogg", ".ogv"))
            ]

            if video_files:
                chosen = random.choice(video_files)
                video_path = os.path.join("assets/videos", chosen)

                with open(video_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")

                html_video = f"""
                <video width="220" autoplay loop muted playsinline
                       style="border-radius:12px;">
                    <source src="data:video/mp4;base64,{b64}" type="video/mp4">
                </video>
                """

                st.session_state["current_video"] = html_video
                video_container.markdown(html_video, unsafe_allow_html=True)
        except Exception as e:
            st.warning(f"No se pudo reproducir el video: {e}")

        # Llamada a Gemini (ahora con web search habilitado)
        sys_prompt = (
            "Eres NICO, asistente institucional de la Universidad Michoacana de San Nicolás de Hidalgo (UMSNH). "
            "Responde siempre en español, de forma clara, breve y amable. Cuando lo necesites usa búsqueda web. "
            "Consulta y prioriza SIEMPRE estos sitios oficiales y sus subpáginas: "
            "https://www.umich.mx "
            "https://umich.mx/unidades-administrativas/ "
            "https://www.gacetanicolaita.umich.mx/ "
            "https://www.dce.umich.mx/ "
            "https://www.dce.umich.mx/guias/guia-inscripciones-en-linea/ "
            "https://www.dce.umich.mx/guias/guia-para-generar-orden-de-pago-de-certificados-cartas-de-pasante-y-certificacion-de-firmas/ "
            "https://siia.umich.mx "
            "https://siia.umich.mx/escolar/convocatoria_23-24/convocatoria-bachillerato.html "
            "https://www.bachillerato.umich.mx/index.php/planteles "
            "https://www.colegio.umich.mx/ "
            "https://www.umich.mx/oferta-med.html "
            "https://www.umich.mx/oferta-sup.html "
            "https://www.umich.mx/oferta-posgrado.html "
            "Si la respuesta se basa en información encontrada en la web, menciónalo brevemente al final."
        )
        full_prompt = f"{sys_prompt}\n\nUsuario: {user_msg}"

        reply = gemini_generate(
            full_prompt,
            st.session_state["temperature"],
            st.session_state["top_p"],
            st.session_state["max_tokens"],
        )

                # 👋 Saludo único SOLO al iniciar sesión
        name = st.session_state["profile"].get("name", "")
        if not st.session_state["greeted"]:
            # saludo completo SOLO al inicio de sesión
            saludo = f"Hola {name}, soy NICO, tu asistente virtual de la Universidad Michoacana.

" if name else "Hola, soy NICO.

"
            reply = saludo + (reply or "")
            st.session_state["greeted"] = True
        else:
            # saludos naturales sin exagerar en mensajes posteriores
            if name:
                reply = f"{name}, {reply}"

        # Guardar respuesta del asistente
        st.session_state["history"].append(
            {"role": "assistant", "content": reply}
        )

        st.rerun()

    # Mostrar historial (máx. 20 mensajes)
    for msg in reversed(st.session_state["history"][-20:]):
        if msg["role"] == "user":
            st.chat_message("user").markdown(msg["content"])
        else:
            with st.chat_message("assistant"):
                st.markdown(
                    f"<div class='chat-bubble'>{msg['content']}</div>",
                    unsafe_allow_html=True,
                )

                # Voz en el navegador (masculina/neutra/grave + sync video)
                if st.session_state["voice_on"]:
                    speak_browser(msg["content"])
            break
