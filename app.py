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
    return flow


def ensure_session_defaults():
    st.session_state.setdefault("logged", False)
    st.session_state.setdefault("profile", {})
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("voice_on", True)
    st.session_state.setdefault("temperature", 0.7)
    st.session_state.setdefault("top_p", 0.9)
    st.session_state.setdefault("max_tokens", 256)
    st.session_state.setdefault("current_video", None)
    st.session_state.setdefault("open_cfg", False)
    st.session_state.setdefault("greeted", False)
    st.session_state.setdefault("user_input", "")


def header_html():
    video_path = "assets/videos/nico_header_video.mp4"
    if os.path.exists(video_path):
        with open(video_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        video_tag = f"""
        <video class="nico-video" autoplay loop muted playsinline>
            <source src="data:video/mp4;base64,{b64}" type="video/mp4">
        </video>
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
    .nico-video {{
        width:56px;
        height:56px;
        border-radius:50%;
        object-fit:cover;
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


# ------------------------------------------------------------
# Gemini con búsqueda web
# ------------------------------------------------------------
def gemini_generate(prompt, temperature, top_p, max_tokens):

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": float(temperature),
            "topP": float(top_p),
            "maxOutputTokens": int(max_tokens),
        },
        "tools": [
            {"google_search": {}}
        ],
    }

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }

    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=40)
        resp.raise_for_status()
        data = resp.json()

        text = ""
        for c in data.get("candidates", []):
            for p in c.get("content", {}).get("parts", []):
                text += p.get("text", "")

        return text.strip()

    except Exception as e:
        return f"⚠️ Error con Gemini: {e}"


# ------------------------------------------------------------
# Voz y sincronización con video
# ------------------------------------------------------------
def speak_browser(text):

    if not text:
        return

    payload = json.dumps(text)

    js = f"""
    <script>
    const utter = new SpeechSynthesisUtterance({payload});
    utter.rate = 0.95;
    utter.pitch = 0.65;

    const vid = parent.document.getElementById("nico-main-video");

    utter.onstart = () => {{
        if (vid) vid.play();
    }};

    utter.onend = () => {{
        if (vid) vid.pause();
    }};

    speechSynthesis.speak(utter);
    </script>
    """

    components.html(js, height=0)


# ============================================================
# Lógica principal
# ============================================================

ensure_session_defaults()

# OAuth
params = st.experimental_get_query_params()

if "code" in params:
    try:
        flow = get_flow()
        flow.fetch_token(code=params["code"][0])
        creds = flow.credentials

        req = grequests.Request()
        idinfo = id_token.verify_oauth2_token(creds.id_token, req, CLIENT_ID)

        st.session_state["logged"] = True
        st.session_state["profile"] = {
            "email": idinfo["email"],
            "name": idinfo["name"],
            "picture": idinfo["picture"],
        }

        st.experimental_set_query_params()
        st.rerun()

    except Exception as e:
        st.error(f"Error OAuth: {e}")

# ------------------------------------------------------------
# Login
# ------------------------------------------------------------
if not st.session_state["logged"]:
    login_view()
    st.stop()


# ------------------------------------------------------------
# Interfaz principal
# ------------------------------------------------------------
st.markdown(header_html(), unsafe_allow_html=True)

conv_col, video_col = st.columns([0.7, 0.3])

with video_col:
    video_container = st.empty()
    if st.session_state["current_video"]:
        video_container.markdown(st.session_state["current_video"], unsafe_allow_html=True)

with conv_col:

    # Controles
    c1, c2, c3 = st.columns([0.1, 0.1, 0.8])

    with c1:
        if st.button("🎙️ Voz ON" if st.session_state["voice_on"] else "🔇 Voz OFF"):
            st.session_state["voice_on"] = not st.session_state["voice_on"]

    with c2:
        if st.button("⚙️ Config"):
            st.session_state["open_cfg"] = True

    with c3:
        st.write(f"Bienvenido, **{st.session_state['profile'].get('name', '')}**")

    if st.session_state["open_cfg"]:
        with st.popover("Configuración del Modelo"):
            st.slider("Temperatura", 0.0, 1.5, key="temperature")
            st.slider("Top-P", 0.0, 1.0, key="top_p")
            st.slider("Máx. tokens", 64, 2048, key="max_tokens", step=32)
            if st.button("Cerrar"):
                st.session_state["open_cfg"] = False

    st.markdown("### 💬 Conversación")

    # ---------------------------
    # INPUT + ENVIAR + BORRAR
    # ---------------------------
    inp_col, send_col, del_col = st.columns([0.7, 0.15, 0.15])

    with inp_col:
        st.session_state["user_input"] = st.text_input(
            "Escribe tu pregunta:",
            st.session_state["user_input"]
        )

    with send_col:
        send = st.button("Enviar", use_container_width=True)

    with del_col:
        clear = st.button("Borrar", use_container_width=True)

    # Borrar historial
    if clear:
        st.session_state["history"] = []
        st.session_state["current_video"] = None
        st.session_state["greeted"] = False
        st.session_state["user_input"] = ""
        st.rerun()

    # Enviar mensaje
    msg = st.session_state["user_input"].strip()

    if send and msg:
        st.session_state["history"].append({"role": "user", "content": msg})

        # Video aleatorio
        try:
            vids = [
                x for x in os.listdir("assets/videos")
                if x.lower().endswith((".mp4", ".webm", ".ogg"))
            ]

            if vids:
                ch = random.choice(vids)
                p = os.path.join("assets/videos", ch)

                with open(p, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")

                html_vid = f"""
                <video id="nico-main-video" width="220" autoplay loop muted playsinline
                       style="border-radius:12px;">
                    <source src="data:video/mp4;base64,{b64}" type="video/mp4">
                </video>
                """

                st.session_state["current_video"] = html_vid
                video_container.markdown(html_vid, unsafe_allow_html=True)

        except:
            pass

        # Gemini
        sys = (
            "Eres NICO, asistente institucional de la Universidad Michoacana de San Nicolás de Hidalgo."
            " Usa búsqueda web cuando sea necesario."
        )

        full = f"{sys}\n\nUsuario: {msg}"

        reply = gemini_generate(full,
                                st.session_state["temperature"],
                                st.session_state["top_p"],
                                st.session_state["max_tokens"])

        # Saludo único
        if not st.session_state["greeted"]:
            nm = st.session_state["profile"].get("name", "")
            saludo = f"Hola {nm}, soy NICO, tu asistente virtual.\n\n"
            reply = saludo + reply
            st.session_state["greeted"] = True

        # Guardar respuesta
        st.session_state["history"].append({"role": "assistant", "content": reply})

        # Limpiar input
        st.session_state["user_input"] = ""
        st.rerun()

    # Mostrar historial
    for h in reversed(st.session_state["history"][-20:]):
        if h["role"] == "user":
            st.chat_message("user").markdown(h["content"])
        else:
            with st.chat_message("assistant"):
                st.markdown(f"<div class='chat-bubble'>{h['content']}</div>",
                            unsafe_allow_html=True)

                if st.session_state["voice_on"]:
                    speak_browser(h["content"])
            break
