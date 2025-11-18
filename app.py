# ============================================================
# NICO OAuth + Gemini (VERSIÓN FINAL - GOOGLE TTS INTEGRADO)
# ============================================================

import os
import re
import urllib.parse
import json
import base64
import random
import requests
import streamlit as st
import tempfile
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
from dotenv import load_dotenv
from speech_utils import synthesize_edge_tts
import uuid

# ------------------------------------------------------------
# 🔧 Streamlit exige que set_page_config esté al inicio
# ------------------------------------------------------------
st.set_page_config(page_title="NICO | Asistente Virtual UMSNH", page_icon="🤖", layout="wide")

# ============================================================
# 🔧 Cargar credencial de Google TTS desde Streamlit Secrets
# ============================================================
if "service_account" in st.secrets:
    json_path = tempfile.NamedTemporaryFile(delete=False)
    json_path.write(json.dumps(st.secrets["service_account"]).encode())
    json_path.flush()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = json_path.name

# ============================================================
# 🔧 FIX 1: Manejar redirección desde /oauth2callback
# ============================================================
_request_uri = os.environ.get("STREAMLIT_SERVER_REQUEST_URI", "")
if "/oauth2callback" in _request_uri:
    parsed = urllib.parse.urlparse(_request_uri)
    query = urllib.parse.parse_qs(parsed.query)
    st.experimental_set_query_params(**query)
    st.experimental_rerun()

# ============================================================
# 🔧 FIX 2: Variables y configuración
# ============================================================
load_dotenv()

CLIENT_ID     = st.secrets.get("GOOGLE_CLIENT_ID", os.getenv("GOOGLE_CLIENT_ID", ""))
CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET", os.getenv("GOOGLE_CLIENT_SECRET", ""))
GOOGLE_REDIRECT_URI = st.secrets.get("GOOGLE_REDIRECT_URI", "https://nicooapp-umsnh.streamlit.app/")

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile"
]

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")
GEMINI_MODEL   = st.secrets.get("GEMINI_MODEL", "gemini-2.0-flash-lite-001")

# ============================================================
# 🔧 Helper: Crear flujo OAuth correctamente
# ============================================================
def get_flow(state=None):
    client_config = {
        "web": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri":  "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [
                "https://nicooapp-umsnh.streamlit.app/",
                "http://localhost:8501/",
                "http://127.0.0.1:8501/"
            ],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=GOOGLE_REDIRECT_URI)
    if state:
        flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow

# ============================================================
# Funciones auxiliares
# ============================================================
def ensure_session_defaults():
    st.session_state.setdefault("logged", False)
    st.session_state.setdefault("profile", {})
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("voice_on", True)
    st.session_state.setdefault("temperature", 0.7)
    st.session_state.setdefault("top_p", 0.9)
    st.session_state.setdefault("max_tokens", 256)

# ============================================================
# UI original — sin modificar nada visual del header
# ============================================================
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
        st.error("Faltan variables OAuth.")
        return

    if "oauth_state" not in st.session_state:
        st.session_state["oauth_state"] = str(uuid.uuid4())

    state_key = st.session_state["oauth_state"]
    flow = get_flow(state=state_key)

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes=False,
        prompt="consent",
        state=state_key
    )

    st.experimental_set_query_params(oauth_state=state_key)
    st.markdown(f"[🔐 Iniciar sesión con Google]({auth_url})")

# ============================================================
# Intercambio OAuth
# ============================================================
def exchange_code_for_token():
    params = st.experimental_get_query_params()
    if "code" not in params:
        return

    try:
        code  = params["code"][0]
        state = params["state"][0]

        if "oauth_state" not in st.session_state:
            st.session_state["oauth_state"] = state

        if state != st.session_state["oauth_state"]:
            st.session_state["oauth_state"] = state

        flow = get_flow(state=state)
        flow.fetch_token(code=code)
        creds = flow.credentials

        request = grequests.Request()
        idinfo  = id_token.verify_oauth2_token(creds.id_token, request, CLIENT_ID)

        st.session_state["logged"]  = True
        st.session_state["profile"] = {
            "email":   idinfo.get("email"),
            "name":    idinfo.get("name"),
            "picture": idinfo.get("picture")
        }

        st.experimental_set_query_params()
        st.rerun()

    except Exception as e:
        st.error(f"Error al autenticar: {e}")

# ============================================================
# Generador Gemini
# ============================================================
def gemini_generate(prompt: str, temperature, top_p, max_tokens):
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    headers  = {"Content-Type": "application/json"}
    payload  = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "topP": top_p,
            "maxOutputTokens": max_tokens
        }
    }

    try:
        r = requests.post(endpoint, headers=headers, json=payload, timeout=30)
        data = r.json()
        text = ""

        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                text += part.get("text", "")

        return text.strip()

    except Exception as e:
        return f"⚠️ Error con Gemini: {e}"

# ============================================================
# Lógica principal
# ============================================================
ensure_session_defaults()
exchange_code_for_token()

if not st.session_state["logged"]:
    login_view()
    st.stop()

st.markdown(header_html(), unsafe_allow_html=True)

conv_col, video_col = st.columns([0.7, 0.3])

with video_col:
    video_container = st.empty()

with conv_col:
    c1, c2, c3 = st.columns([0.1, 0.1, 0.8])

    with c1:
        if st.button("🎙️ Voz: ON" if st.session_state["voice_on"] else "🔇 Voz: OFF"):
            st.session_state["voice_on"] = not st.session_state["voice_on"]

    with c2:
        if st.button("⚙️ Config"):
            st.session_state["open_cfg"] = True

    with c3:
        st.write(f"Bienvenido, **{st.session_state['profile']['name']}**")

    if st.session_state.get("open_cfg"):
        with st.popover("Configuración del Modelo"):
            st.slider("Temperatura", 0.0, 1.5, key="temperature")
            st.slider("Top-P", 0.0, 1.0, key="top_p")
            st.slider("Máx. tokens", 64, 2048, key="max_tokens", step=32)
            if st.button("Cerrar"):
                st.session_state["open_cfg"] = False

    st.markdown("### 💬 Conversación")

    user_msg = st.text_input("Escribe tu pregunta:")

    if st.button("Enviar") and user_msg.strip():

        st.session_state["history"].append({"role": "user", "content": user_msg})

        # --- reproducir video ---

        try:
            video_files = [f for f in os.listdir("assets/videos") if f.endswith(".mp4")]
            if video_files:
                chosen = random.choice(video_files)
                path = f"assets/videos/{chosen}"

                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()

                video_container.markdown(
                    f"""
                    <video width="220" autoplay loop muted playsinline style="border-radius:12px;">
                        <source src="data:video/mp4;base64,{b64}" type="video/mp4">
                    </video>
                    """,
                    unsafe_allow_html=True,
                )
        except:
            pass

        prompt = "Eres NICO, asistente institucional de la UMSNH.\n\nUsuario: " + user_msg
        reply = gemini_generate(
            prompt,
            st.session_state["temperature"],
            st.session_state["top_p"],
            st.session_state["max_tokens"]
        )

        st.session_state["history"].append({"role": "assistant", "content": reply})

        st.rerun()

    # Mostrar historial
    for msg in reversed(st.session_state["history"][-20:]):
        if msg["role"] == "user":
            st.chat_message("user").markdown(msg["content"])

        else:
            with st.chat_message("assistant"):
                st.markdown(f"<div class='chat-bubble'>{msg['content']}</div>", unsafe_allow_html=True)

                if st.session_state["voice_on"]:
                    audio_bytes = synthesize_edge_tts(msg["content"])
                    if audio_bytes:
                        st.audio(audio_bytes, format="audio/mp3")
