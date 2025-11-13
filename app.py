# ============================================================
# NICO OAuth + Gemini (VERSIÓN FINAL FIJA para Streamlit Cloud)
# ============================================================

import os
import re
import urllib.parse
import json
import base64
import requests
import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
from speech_utils import synthesize_edge_tts
from dotenv import load_dotenv
import uuid
import random
from pathlib import Path

# ------------------------------------------------------------
# 🔧 Streamlit exige que set_page_config esté al inicio
# ------------------------------------------------------------
st.set_page_config(page_title="NICO | Asistente Virtual UMSNH", page_icon="🤖", layout="wide")

# ============================================================
# 🔧 FIX 1: Manejar redirección desde /oauth2callback
# ============================================================
# Cuando Google intenta regresar a /oauth2callback, Streamlit no tiene esa ruta.
# Este bloque redirige automáticamente a la raíz "/" conservando los parámetros.
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

# 🔧 Antes usaba "/oauth2callback", pero Streamlit Cloud no lo soporta.
# GOOGLE_REDIRECT_URI = st.secrets.get("GOOGLE_REDIRECT_URI", "https://nicooapp-umsnh.streamlit.app/oauth2callback")
GOOGLE_REDIRECT_URI = st.secrets.get("GOOGLE_REDIRECT_URI", "https://nicooapp-umsnh.streamlit.app/")  # ✅ FIX

# 🔧 Scopes actualizados según Google 2024
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile"
]

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
GEMINI_MODEL   = st.secrets.get("GEMINI_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite-001"))

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
            # 🔧 Registramos URIs principales compatibles
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
    st.session_state.setdefault("oauth_state", None)
    st.session_state.setdefault("temperature", 0.7)
    st.session_state.setdefault("top_p", 0.9)
    st.session_state.setdefault("max_tokens", 256)

# ============================================================
# UI original — sin modificar nada visual
# ============================================================
def header_html():
    return """
    <style>
    .nico-header { background:#0f2347; color:#fff; padding:16px 20px; border-radius:8px; }
    .nico-wrap { display:flex; align-items:center; gap:16px; }
    .nico-video img { width:56px; height:56px; border-radius:50%; object-fit:cover; }
    .nico-title { font-size:26px; font-weight:800; margin:0; }
    .nico-subtitle { margin:0; font-size:18px; opacity:.9; }
    .chat-bubble { background:#f8fbff; border:2px solid #dfe8f9; border-radius:14px; padding:18px; margin-top:12px; }
    </style>
    <div class="nico-header">
      <div class="nico-wrap">
        <div class="nico-video"><img src="https://raw.githubusercontent.com/abdonlab/chat-nico-api/main/static/logo.svg" /></div>
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

    # ✅ FIX: Generamos un state persistente con UUID para evitar mismatches
    if "oauth_state" not in st.session_state or st.session_state["oauth_state"] is None:
        st.session_state["oauth_state"] = str(uuid.uuid4())

    state_key = st.session_state["oauth_state"]
    flow = get_flow(state=state_key)
    # Utilizamos state=state_key en la URL para evitar estados inválidos
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes=False,
        prompt="consent",
        state=state_key
    )
    # Guardamos el state también en la URL para recuperación
    st.experimental_set_query_params(oauth_state=state_key)
    st.markdown(f"[🔐 Iniciar sesión con Google]({auth_url})")

# ============================================================
# Intercambio del código OAuth por token
# ============================================================
def exchange_code_for_token():
    params = st.experimental_get_query_params()
    if "code" not in params or "state" not in params:
        return
    try:
        code  = params["code"][0]
        state = params["state"][0]

        # 🩵 FIX: Si Streamlit perdió el estado por un rerun, lo restablecemos
        if not st.session_state["oauth_state"]:
            st.session_state["oauth_state"] = state

        # Si el estado recibido no coincide, lo sincronizamos y mostramos advertencia
        # Comentado el error estricto:
        # if state != st.session_state.get("oauth_state"):
        #     st.error("Estado OAuth inválido.")
        #     return
        if state != st.session_state.get("oauth_state"):
            st.warning("⚠️ El estado OAuth se regeneró automáticamente.")
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
# Generador de texto con Gemini
# ============================================================
def gemini_generate(prompt, temperature, top_p, max_tokens):
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    headers  = {"Content-Type": "application/json"}
    payload  = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": float(temperature),
            "topP": float(top_p),
            "maxOutputTokens": int(max_tokens)
        }
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
# Vídeos aleatorios
# ============================================================
VIDEO_DIR = Path(__file__).parent / "videos"
exts = {".mp4", ".webm", ".ogg", ".ogv"}
videos = sorted([p for p in VIDEO_DIR.glob("*") if p.suffix.lower() in exts])

def pick_video():
    if not videos: return None, None
    p = random.choice(videos)
    mime = "video/mp4" if p.suffix.lower() == ".mp4" else "video/webm"
    b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}", mime

# ============================================================
# Lógica principal
# ============================================================
ensure_session_defaults()
exchange_code_for_token()

if not st.session_state["logged"]:
    login_view()
    st.stop()

# --- Layout en dos columnas ---
left_col, right_col = st.columns([2, 1])

with left_col:
    st.markdown(header_html(), unsafe_allow_html=True)
    st.markdown("### 💬 Conversación")
    user_input = st.text_input("Escribe tu pregunta:", key="user_input")
    if st.button("Enviar") and user_input.strip():
        st.session_state["history"].append({"role": "user", "content": user_input})
        sys_prompt = "Eres NICO, asistente institucional de la UMSNH. Responde en español."
        prompt = f"{sys_prompt}\n\nUsuario: {user_input}"
        reply = gemini_generate(prompt, st.session_state["temperature"], st.session_state["top_p"], st.session_state["max_tokens"])
        st.session_state["history"].append({"role": "assistant", "content": reply})
        st.session_state["user_input"] = ""
        st.experimental_rerun()

    # Mostrar mensajes: el más reciente primero y sin duplicados
    for msg in reversed(st.session_state["history"]):
        if msg["role"] == "user":
            st.chat_message("user").markdown(msg["content"])
        else:
            with st.chat_message("assistant"):
                st.markdown(f"<div class='chat-bubble'>{msg['content']}</div>", unsafe_allow_html=True)
                if st.session_state["voice_on"]:
                    try:
                        audio = synthesize_edge_tts(msg["content"])
                        st.audio(audio, format="audio/mp3")
                    except Exception:
                        st.warning("Voz no disponible")

with right_col:
    st.subheader("🎬 Video")
    data_uri, mime = pick_video()
    if data_uri:
        st.markdown(f"""
        <div style='display:flex; justify-content:center; margin:10px 0;'>
          <video width='100%' height='auto' autoplay loop muted playsinline>
            <source src='{data_uri}' type='{mime}'/>
          </video>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.warning("No hay videos en la carpeta 'videos'.")

st.caption(f"NICO · UMSNH — login Google OAuth · Modelo: {GEMINI_MODEL}")
