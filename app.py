# ============================================================
# NICO OAuth + Gemini (VERSIÓN FINAL FIJA para Streamlit Cloud)
# ============================================================

import os
import re
import urllib.parse
import json
import base64
import random  # para elegir video aleatorio
import requests
import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
from speech_utils import synthesize_edge_tts
from dotenv import load_dotenv
import uuid  # Necesario para generar un state único

# ------------------------------------------------------------
# Streamlit exige que set_page_config esté al inicio
# ------------------------------------------------------------
st.set_page_config(page_title="NICO | Asistente Virtual UMSNH", page_icon="🤖", layout="wide")

# ============================================================
# FIX 1: Manejar redirección desde /oauth2callback
# ============================================================
_request_uri = os.environ.get("STREAMLIT_SERVER_REQUEST_URI", "")
if "/oauth2callback" in _request_uri:
    parsed = urllib.parse.urlparse(_request_uri)
    query = urllib.parse.parse_qs(parsed.query)
    st.experimental_set_query_params(**query)
    st.experimental_rerun()

# ============================================================
# FIX 2: Variables y configuración
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

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
GEMINI_MODEL   = st.secrets.get("GEMINI_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite-001"))

# ============================================================
# Helper OAuth
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
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI
    )
    if state:
        flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow

# ============================================================
# Session defaults
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
# Header HTML
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
# LOGIN VIEW
# ============================================================
def login_view():
    st.markdown(header_html(), unsafe_allow_html=True)
    st.info("Inicia sesión con tu cuenta de Google para usar NICO.")

    if not CLIENT_ID or not CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
        st.error("Faltan GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET/GOOGLE_REDIRECT_URI.")
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
# EXCHANGE CODE
# ============================================================
def exchange_code_for_token():
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
            "picture": idinfo.get("picture")
        }

        st.experimental_set_query_params()
        st.rerun()

    except Exception as e:
        st.error(f"Error al autenticar: {e}")

# ============================================================
# GEMINI TEXT GENERATOR
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
            "maxOutputTokens": int(max_tokens)
        }
    }

    try:
        r = requests.post(endpoint, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        txt = ""
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                txt += part.get("text", "")
        return txt.strip() or "No obtuve respuesta."
    except Exception as e:
        return f"⚠️ Error con Gemini: {e}"

# ============================================================
# MAIN LOGIC (chat + video dinámico)
# ============================================================
ensure_session_defaults()
exchange_code_for_token()

if not st.session_state.get("logged"):
    login_view()
    st.stop()

# Header
st.markdown(header_html(), unsafe_allow_html=True)

# Creamos columnas: conversación (izq) + video (der)
conv_col, video_col = st.columns([0.7, 0.3])

with video_col:
    # video pequeño estático que solo se actualiza en cada respuesta
    video_container = st.empty()
