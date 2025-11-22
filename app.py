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


def header_html():
    return f"""
    <style>
    .nico-header {{ background:#0f2347;color:#fff;padding:16px 20px;border-radius:8px; }}
    .nico-wrap {{ display:flex;align-items:center;gap:16px; }}
    .nico-video {{ width:56px;height:56px;border-radius:50%;object-fit:cover; }}
    .nico-title {{ font-size:26px;font-weight:800;margin:0; }}
    .nico-subtitle {{ margin:0;font-size:18px;opacity:.9; }}
    .chat-bubble {{ background:#f8fbff;border:2px solid #dfe8f9;border-radius:14px;padding:18px;margin-top:12px; }}
    </style>
    <div class="nico-header">
        <div class="nico-wrap">
            <img class="nico-video" src="assets/img/nico_icon.png" />
            <div>
                <p class="nico-title">NICO</p>
                <p class="nico-subtitle">Asistente Virtual UMSNH</p>
            </div>
        </div>
    </div>
    """


def login_view():
    st.markdown(header_html(), unsafe_allow_html=True)
    st.info("Inicia sesión con tu cuenta de Google para usar NICO.")

    if not CLIENT_ID or not CLIENT_SECRET:
        st.error("Faltan variables OAuth.")
        return

    if "oauth_state" not in st.session_state:
        st.session_state["oauth_state"] = str(uuid.uuid4())

    state = st.session_state["oauth_state"]
    flow = get_flow(state=state)

    auth_url, _ = flow.authorization_url(
        access_type="offline", include_granted_scopes=False, prompt="consent", state=state
    )

    st.experimental_set_query_params(oauth_state=state)

    st.markdown(f"[🔐 Iniciar sesión con Google]({auth_url})")


def exchange_code_for_token():
    params = st.experimental_get_query_params()
    if "code" not in params:
        return

    try:
        code = params["code"][0]
        state = params.get("state", [""])[0]

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
# Gemini API
# ============================================================

def gemini_generate(prompt, temperature, top_p, max_tokens):
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": float(temperature),
            "topP": float(top_p),
            "maxOutputTokens": int(max_tokens),
        },
        "tools": [{"google_search": {}}],
    }

    try:
        r = requests.post(endpoint, headers=headers, json=payload, timeout=40)
        r.raise_for_status()
        data = r.json()
        text = ""
        for c in data.get("candidates", []):
            for p in c.get("content", {}).get("parts", []):
                text += p.get("text", "")
        return text.strip() or "No obtuve respuesta del modelo."
    except Exception as e:
        return f"⚠️ Error con Gemini: {e}"


# ============================================================
# Web Speech (voz)
# ============================================================

def speak_browser(text):
    if not text:
        return

    payload = json.dumps(text)
    js = f"""
    <script>
    (function() {{
        const text = {payload};
        const synth = window.speechSynthesis;
        if (!synth) return;
        function speak() {{
            synth.cancel();
            const u = new SpeechSynthesisUtterance(text);
            u.rate = 0.95;
            u.pitch = 0.65;
            synth.speak(u);
        }}
        if (synth.getVoices().length===0) {{
            synth.onvoiceschanged = speak;
        }} else {{ speak(); }}
    }})();
    </script>
    """
    components.html(js, height=0)


# ============================================================
# App Principal
# ============================================================

ensure_session_defaults()
exchange_code_for_token()

if not st.session
