# ============================================================
# NICO OAuth + Gemini + Videos (VERSIÓN AJUSTADA)
# ============================================================

import os
import re
import urllib.parse
import json
import base64
import random
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
from speech_utils import synthesize_edge_tts
from dotenv import load_dotenv

# ------------------------------------------------------------
# 🔧 Streamlit exige que set_page_config esté al inicio
# ------------------------------------------------------------
st.set_page_config(
    page_title="NICO | Asistente Virtual UMSNH",
    page_icon="🤖",
    layout="wide"
)

# ============================================================
# 🔧 FIX 1: Manejar redirección desde /oauth2callback en Cloud
# ============================================================
_request_uri = os.environ.get("STREAMLIT_SERVER_REQUEST_URI", "")
if _request_uri and "/oauth2callback" in _request_uri:
    # Redirige a la raíz conservando ?code&state
    parsed = urllib.parse.urlparse(_request_uri)
    query = urllib.parse.parse_qs(parsed.query)
    st.experimental_set_query_params(**query)
    st.experimental_rerun()

# ============================================================
# 🔧 Variables y configuración generales
# ============================================================
load_dotenv()

CLIENT_ID = st.secrets.get("GOOGLE_CLIENT_ID", os.getenv("GOOGLE_CLIENT_ID", ""))
CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET", os.getenv("GOOGLE_CLIENT_SECRET", ""))

# Antes usaba "/oauth2callback", pero en Streamlit Cloud se maneja mejor la raíz
# GOOGLE_REDIRECT_URI = st.secrets.get("GOOGLE_REDIRECT_URI", "https://nicooapp-umsnh.streamlit.app/oauth2callback")
GOOGLE_REDIRECT_URI = st.secrets.get(
    "GOOGLE_REDIRECT_URI",
    "https://nicooapp-umsnh.streamlit.app/"
)

# Scopes nuevos correctos (los que te marcaba el error de "Scope has changed")
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
GEMINI_MODEL = st.secrets.get("GEMINI_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite-001"))

# ============================================================
# 🔧 Configuración de videos (como en tu otro chat)
# ============================================================
ROOT = Path(__file__).parent
VIDEO_DIR = ROOT / "videos"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

VIDEO_EXTS = {".mp4", ".webm", ".ogg", ".ogv"}


def listar_videos():
    """Devuelve una lista de rutas de videos válidos en la carpeta videos/."""
    return sorted([p for p in VIDEO_DIR.glob("*") if p.suffix.lower() in VIDEO_EXTS])


def pick_video_data_uri():
    """Elige un video al azar y lo devuelve como data URI + mime."""
    paths = listar_videos()
    if not paths:
        return None, None
    p = random.choice(paths)
    if p.suffix.lower() == ".mp4":
        mime = "video/mp4"
    elif p.suffix.lower() == ".webm":
        mime = "video/webm"
    else:
        mime = "video/ogg"
    b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}", mime


# ============================================================
# 🔧 Helper: Crear flujo OAuth correctamente
# ============================================================
def get_flow(state=None):
    client_config = {
        "web": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            # URIs registradas en Google Cloud
            "redirect_uris": [
                "https://nicooapp-umsnh.streamlit.app/",
                "http://localhost:8501/",
                "http://127.0.0.1:8501/"
            ],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI
    )
    if state:
        flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow


# ============================================================
# Funciones auxiliares de sesión
# ============================================================
def ensure_session_defaults():
    st.session_state.setdefault("logged", False)
    st.session_state.setdefault("profile", {})
    st.session_state.setdefault("history", [])      # historial de mensajes
    st.session_state.setdefault("voice_on", False)
    st.session_state.setdefault("temperature", 0.7)
    st.session_state.setdefault("top_p", 0.9)
    st.session_state.setdefault("max_tokens", 256)
    st.session_state.setdefault("last_video_html", "")  # último video renderizado


# ============================================================
# UI original — NO se modifica el estilo del header
# ============================================================
def header_html():
    # Aquí no toco tu estética
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
    .nico-header {{ background:#0f2347; color:#fff; padding:16px 20px; border-radius:8px; }}
    .nico-wrap {{ display:flex; align-items:center; gap:16px; }}
    .nico-video,.nico-placeholder {{ width:56px; height:56px; border-radius:50%; background:#fff; object-fit:cover; }}
    .nico-title {{ font-size:26px; font-weight:800; margin:0; }}
    .nico-subtitle {{ margin:0; font-size:18px; opacity:.9; }}
    .chat-bubble {{ background:#f8fbff; border:2px solid #dfe8f9; border-radius:14px; padding:18px; margin-top:12px; }}
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


# ============================================================
# Vista de login
# ============================================================
def login_view():
    st.markdown(header_html(), unsafe_allow_html=True)
    st.info("Inicia sesión con tu cuenta de Google para usar **NICO**.")

    if not CLIENT_ID or not CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
        st.error("Faltan GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET/GOOGLE_REDIRECT_URI.")
        return

    flow = get_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes=False,
        prompt="consent"
    )
    st.session_state["oauth_state"] = state
    st.markdown(f"[🔐 Iniciar sesión con Google]({auth_url})")


# ============================================================
# Intercambio del código OAuth por token
# ============================================================
def exchange_code_for_token():
    params = st.experimental_get_query_params()
    if "code" not in params or "state" not in params:
        return
    try:
        code = params["code"][0]
        state = params["state"][0]
        if state != st.session_state.get("oauth_state"):
            st.error("Estado OAuth inválido.")
            return

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

        st.experimental_set_query_params()  # limpia ?code&state
        st.rerun()

    except Exception as e:
        st.error(f"Error al autenticar: {e}")


# ============================================================
# Generador de texto con Gemini
# ============================================================
def gemini_generate(prompt: str, temperature: float, top_p: float, max_tokens: int) -> str:
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": float(temperature),
            "topP": float(top_p),
            "maxOutputTokens": int(max_tokens),
        },
    }
    try:
        r = requests.post(endpoint, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        text = ""
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                text += part.get("text", "")
        return text.strip() or "No obtuve respuesta."
    except Exception as e:
        return f"⚠️ Error con Gemini: {e}"


# ============================================================
# Lógica principal
# ============================================================
ensure_session_defaults()
exchange_code_for_token()

if not st.session_state.get("logged"):
    login_view()
    st.stop()

# ------------------------------------------------------------
# HEADER (sin cambios visuales)
# ------------------------------------------------------------
st.markdown(header_html(), unsafe_allow_html=True)

# Barra de controles (voz / config)
c1, c2, c3 = st.columns([0.15, 0.15, 0.7])
with c1:
    if st.button("🎙️ Voz: ON" if st.session_state["voice_on"] else "🔇 Voz: OFF"):
        st.session_state["voice_on"] = not st.session_state["voice_on"]
with c2:
    if st.button("⚙️ Config"):
        st.session_state["open_cfg"] = True
with c3:
    st.write(
        f"Bienvenido, **{st.session_state['profile'].get('name', 'Usuario')}**"
    )

if st.session_state.get("open_cfg"):
    with st.popover("Configuración del Modelo"):
        st.slider("Temperatura", 0.0, 1.5, key="temperature")
        st.slider("Top-P", 0.0, 1.0, key="top_p")
        st.slider("Máx. tokens", 64, 2048, key="max_tokens", step=32)
        if st.button("Cerrar"):
            st.session_state["open_cfg"] = False

# ------------------------------------------------------------
# Conversación + Video en columnas
# ------------------------------------------------------------
col_chat, col_video = st.columns([0.7, 0.3])

# ===== Columna del CHAT =====
with col_chat:
    st.markdown("## 💬 Conversación")

    user_input = st.text_input("Escribe tu pregunta:", key="user_input")
    send_clicked = st.button("Enviar", key="send_button")

# ===== Columna del VIDEO =====
with col_video:
    st.markdown("### 🎬 NICO en acción")
    video_placeholder = st.empty()
    # Si ya había un video cargado de la última interacción, lo mostramos
    if st.session_state.get("last_video_html"):
        video_placeholder.markdown(
            st.session_state["last_video_html"], unsafe_allow_html=True
        )

# ------------------------------------------------------------
# Cuando el usuario envía una pregunta
# ------------------------------------------------------------
if send_clicked and user_input.strip():
    # 1) Elegir y mostrar video pequeño a la derecha
    data_uri, mime = pick_video_data_uri()
    if data_uri:
        video_html = f"""
        <video class="nico-video-chat" width="220" height="124"
               autoplay loop muted playsinline
               style="border-radius:16px;box-shadow:0 0 10px rgba(0,0,0,0.3);">
            <source src="{data_uri}" type="{mime}">
        </video>
        """
        st.session_state["last_video_html"] = video_html
        # Lo dibujamos inmediatamente
        video_placeholder.markdown(video_html, unsafe_allow_html=True)
    else:
        st.session_state["last_video_html"] = ""
        video_placeholder.warning("No hay videos en la carpeta `videos/`.")

    # 2) Guardar mensaje del usuario en el historial
    st.session_state["history"].append({"role": "user", "content": user_input})

    # 3) Generar respuesta
    sys_prompt = (
        "Eres NICO, asistente institucional de la UMSNH. "
        "Responde en español de manera clara y amable."
    )
    full_prompt = sys_prompt + "\n\nUsuario: " + user_input

    reply = gemini_generate(
        full_prompt,
        st.session_state["temperature"],
        st.session_state["top_p"],
        st.session_state["max_tokens"],
    )

    # 4) Guardar respuesta en el historial
    st.session_state["history"].append({"role": "assistant", "content": reply})

    # 5) Detener video al terminar la respuesta
    pause_js = """
    <script>
    const vids = window.parent.document.querySelectorAll('video.nico-video-chat');
    vids.forEach(v => { v.pause(); v.currentTime = 0; });
    </script>
    """
    components.html(pause_js, height=0)

    # 6) Limpiar la caja de texto para la siguiente pregunta
    st.session_state["user_input"] = ""
    st.experimental_rerun()

# ------------------------------------------------------------
# Mostrar historial (última respuesta primero)
# ------------------------------------------------------------
with col_chat:
    # Tomamos últimas 20 entradas y las invertimos para que la más reciente quede arriba
    for msg in reversed(st.session_state["history"][-20:]):
        if msg["role"] == "user":
            st.chat_message("user").markdown(msg["content"])
        else:
            with st.chat_message("assistant"):
                st.markdown(
                    f"<div class='chat-bubble'>{msg['content']}</div>",
                    unsafe_allow_html=True,
                )
                if st.session_state["voice_on"]:
                    try:
                        audio_bytes = synthesize_edge_tts(msg["content"])
                        st.audio(audio_bytes, format="audio/mp3")
                    except Exception as e:
                        st.warning(f"Voz no disponible: {e}")

# ------------------------------------------------------------
# Pie de página
# ------------------------------------------------------------
st.caption(
    f"NICO · UMSNH — login Google OAuth · Modelo: {GEMINI_MODEL}"
)
