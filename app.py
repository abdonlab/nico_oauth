# ============================================================
# NICO OAuth + Gemini (VERSIÓN FINAL CON VIDEO)
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
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
from speech_utils import synthesize_edge_tts
from dotenv import load_dotenv
import uuid

# ------------------------------------------------------------
# 🔧 Streamlit exige que set_page_config esté al inicio
# ------------------------------------------------------------
st.set_page_config(page_title="NICO | Asistente Virtual UMSNH", page_icon="🤖", layout="wide")

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

GOOGLE_REDIRECT_URI = st.secrets.get(
    "GOOGLE_REDIRECT_URI",
    "https://nicooapp-umsnh.streamlit.app/"
)

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile"
]

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
GEMINI_MODEL   = st.secrets.get("GEMINI_MODEL", "gemini-2.0-flash-lite-001")

# ============================================================
# 🔧 VIDEO — NUEVO MÓDULO
# ============================================================

ROOT = Path(__file__).parent
VIDEO_DIR = ROOT / "videos"
VIDEO_DIR.mkdir(exist_ok=True)

VIDEO_EXTS = {".mp4", ".webm", ".ogg"}

def pick_video_data_uri():
    videos = [p for p in VIDEO_DIR.glob("*") if p.suffix.lower() in VIDEO_EXTS]
    if not videos:
        return None, None
    vid = random.choice(videos)
    mime = "video/mp4" if vid.suffix.lower() == ".mp4" else "video/webm"
    b64 = base64.b64encode(vid.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}", mime


# ============================================================
# Helper: Crear flujo OAuth
# ============================================================
def get_flow(state=None):
    cfg = {
        "web": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [
                "https://nicooapp-umsnh.streamlit.app/",
                "http://localhost:8501/",
                "http://127.0.0.1:8501/"
            ]
        }
    }
    flow = Flow.from_client_config(cfg, scopes=SCOPES, redirect_uri=GOOGLE_REDIRECT_URI)
    return flow

# ============================================================
# Auxiliares Session
# ============================================================
def ensure_session_defaults():
    st.session_state.setdefault("logged", False)
    st.session_state.setdefault("profile", {})
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("voice_on", True)
    st.session_state.setdefault("temperature", 0.7)
    st.session_state.setdefault("top_p", 0.9)
    st.session_state.setdefault("max_tokens", 256)
    st.session_state.setdefault("video_html", "")   # 🆕 video actual


# ============================================================
# HEADER (NO SE MODIFICA NADA)
# ============================================================
def header_html():
    video_path = "assets/videos/nico_header_video.mp4"
    if os.path.exists(video_path):
        with open(video_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        video_tag = f"""
        <video class="nico-video" autoplay loop muted playsinline>
            <source src="data:video/mp4;base64,{b64}">
        </video>
        """
    else:
        video_tag = "<div class='nico-placeholder'></div>"

    return f"""
    <style>
    .nico-header {{ background:#0f2347; color:#fff; padding:16px 20px; border-radius:8px; }}
    .nico-wrap {{ display:flex; align-items:center; gap:16px; }}
    .nico-video,.nico-placeholder {{ width:56px; height:56px; border-radius:50%; }}
    .chat-bubble {{
        background:#f8fbff; border:2px solid #dfe8f9;
        border-radius:14px; padding:18px; margin-top:12px;
    }}
    </style>

    <div class="nico-header">
      <div class="nico-wrap">
        {video_tag}
        <div>
          <p class="nico-title" style="font-size:26px;font-weight:800">NICO</p>
          <p class="nico-subtitle" style="font-size:18px;opacity:.9">Asistente Virtual UMSNH</p>
        </div>
      </div>
    </div>
    """

# ============================================================
# Login View
# ============================================================
def login_view():
    st.markdown(header_html(), unsafe_allow_html=True)
    st.info("Inicia sesión con tu cuenta de Google para usar NICO.")

    if "oauth_state" not in st.session_state:
        st.session_state["oauth_state"] = str(uuid.uuid4())

    state = st.session_state["oauth_state"]
    flow = get_flow(state)

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes=False,
        prompt="consent",
        state=state
    )

    st.markdown(f"[🔐 Iniciar sesión con Google]({auth_url})")

# ============================================================
# Intercambio de token
# ============================================================
def exchange_code():
    params = st.experimental_get_query_params()
    if "code" not in params or "state" not in params:
        return

    try:
        code  = params["code"][0]
        state = params["state"][0]

        flow = get_flow(state)
        flow.fetch_token(code=code)
        creds = flow.credentials

        req = grequests.Request()
        idinfo = id_token.verify_oauth2_token(
            creds.id_token, req, CLIENT_ID
        )

        st.session_state["logged"]  = True
        st.session_state["profile"] = {
            "email": idinfo.get("email"),
            "name":  idinfo.get("name"),
            "picture": idinfo.get("picture")
        }

        st.experimental_set_query_params()
        st.rerun()

    except Exception as e:
        st.error(f"Error: {e}")

# ============================================================
# Gemini
# ============================================================
def gemini_generate(prompt, temp, top_p, max_tokens):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts":[{"text": prompt}]}],
        "generationConfig":{
            "temperature": temp,
            "topP": top_p,
            "maxOutputTokens": max_tokens
        }
    }

    try:
        r = requests.post(url, json=payload)
        r.raise_for_status()
        data = r.json()

        text = ""
        for c in data.get("candidates", []):
            for p in c.get("content", {}).get("parts", []):
                text += p.get("text", "")
        return text or "No obtuve respuesta."

    except Exception as e:
        return f"⚠️ Error: {e}"

# ============================================================
# MAIN
# ============================================================
ensure_session_defaults()
exchange_code()

if not st.session_state["logged"]:
    login_view()
    st.stop()

# HEADER
st.markdown(header_html(), unsafe_allow_html=True)

# BOTONES SUPERIORES
c1, c2, c3 = st.columns([0.1, 0.1, 0.8])
with c1:
    if st.button("🔇 Voz ON" if st.session_state["voice_on"] else "🔊 Voz OFF"):
        st.session_state["voice_on"] = not st.session_state["voice_on"]
with c2:
    if st.button("⚙️ Config"):
        st.session_state["cfg_open"] = True
with c3:
    st.write(f"Bienvenido **{st.session_state['profile'].get('name')}**")

if st.session_state.get("cfg_open"):
    with st.popover("Ajustes del Modelo"):
        st.slider("Temperatura", 0.0, 1.5, key="temperature")
        st.slider("Top-P",       0.0, 1.0, key="top_p")
        st.slider("Máx tokens",  64, 2048, key="max_tokens", step=32)
        if st.button("Cerrar"): st.session_state["cfg_open"] = False

# ============================================================
# 📌 Conversación + VIDEO 🆕
# ============================================================

col_chat, col_video = st.columns([0.7, 0.3])

with col_chat:
    st.markdown("### 💬 Conversación")
    user_msg = st.text_input("Escribe tu pregunta:")

    if st.button("Enviar") and user_msg.strip():

        # ---------- VIDEO: Seleccionar y mostrar ----------
        data_uri, mime = pick_video_data_uri()
        if data_uri:
            video_html = f"""
            <video autoplay loop muted playsinline width="220" height="130"
                   class="nico-chat-video"
                   style="border-radius:14px;box-shadow:0 0 12px rgba(0,0,0,0.25);">
                <source src="{data_uri}" type="{mime}">
            </video>
            """
            st.session_state["video_html"] = video_html

        # ---------- Guardar pregunta ----------
        st.session_state["history"].append({"role":"user", "content":user_msg})

        # ---------- Generar respuesta ----------
        prompt = f"Eres NICO, asistente institucional de la UMSNH.\nUsuario: {user_msg}"
        reply = gemini_generate(prompt,
                                st.session_state["temperature"],
                                st.session_state["top_p"],
                                st.session_state["max_tokens"])

        st.session_state["history"].append({"role":"assistant", "content":reply})

        # ---------- Pausar video al terminar ----------
        stop_js = """
        <script>
        const vids = window.parent.document.querySelectorAll('.nico-chat-video');
        vids.forEach(v => { v.pause(); v.currentTime = 0; });
        </script>
        """
        st.components.v1.html(stop_js, height=0)
        st.rerun()
# --------- VIDEO A LA DERECHA ---------
with col_video:
    st.markdown("### 🎬 NICO en acción")
    st.markdown(st.session_state["video_html"], unsafe_allow_html=True)
