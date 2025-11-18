# ============================================================
# NICO OAuth + Gemini + Voz Masculina + Video Sync (VERSIÓN FINAL)
# ============================================================

import os
import re
import urllib.parse
import json
import base64
import random
import requests
import streamlit as st
import streamlit.components.v1 as components
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
from dotenv import load_dotenv
import uuid

# ------------------------------------------------------------
# Configuración inicial
# ------------------------------------------------------------
st.set_page_config(page_title="NICO | Asistente Virtual UMSNH", page_icon="🤖", layout="wide")
load_dotenv()

_request_uri = os.environ.get("STREAMLIT_SERVER_REQUEST_URI", "")
if "/oauth2callback" in _request_uri:
    parsed = urllib.parse.urlparse(_request_uri)
    query = urllib.parse.parse_qs(parsed.query)
    st.experimental_set_query_params(**query)
    st.experimental_rerun()

# ------------------------------------------------------------
# Credenciales OAuth
# ------------------------------------------------------------
CLIENT_ID     = st.secrets.get("GOOGLE_CLIENT_ID")
CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = st.secrets.get("GOOGLE_REDIRECT_URI")

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile"
]

# Gemini
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")
GEMINI_MODEL   = st.secrets.get("GEMINI_MODEL", "gemini-2.0-flash-lite-001")

# ------------------------------------------------------------
# Funciones
# ------------------------------------------------------------
def get_flow(state=None):
    client_config = {
        "web": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri":  "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [
                GOOGLE_REDIRECT_URI,
                "http://localhost:8501/",
                "http://127.0.0.1:8501/"
            ],
        }
    }
    return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=GOOGLE_REDIRECT_URI)


def ensure_defaults():
    st.session_state.setdefault("logged", False)
    st.session_state.setdefault("profile", {})
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("voice_on", True)
    st.session_state.setdefault("temperature", 0.7)
    st.session_state.setdefault("top_p", 0.9)
    st.session_state.setdefault("max_tokens", 256)
    st.session_state.setdefault("current_video", None)


def header_html():
    return """
    <style>
    .nico-header { background:#0f2347; color:#fff; padding:16px 20px; border-radius:8px; }
    .nico-wrap { display:flex; align-items:center; gap:16px; }
    .nico-title { font-size:26px; font-weight:800; margin:0; }
    .nico-subtitle { margin:0; font-size:18px; opacity:.9; }
    .chat-bubble { background:#f8fbff; border:2px solid #dfe8f9; border-radius:14px;
                   padding:18px; margin-top:12px; }
    </style>

    <div class="nico-header">
        <div class="nico-wrap">
            <img src="https://umich.mx/wp-content/uploads/2023/04/cropped-escudo-favicon.png"
                 width="56" height="56" style="border-radius:50%;" />
            <div>
                <p class="nico-title">NICO</p>
                <p class="nico-subtitle">Asistente Virtual UMSNH</p>
            </div>
        </div>
    </div>
    """


def login_view():
    st.markdown(header_html(), unsafe_allow_html=True)

    st.info("Inicia sesión con Google para usar NICO.")

    if "oauth_state" not in st.session_state:
        st.session_state["oauth_state"] = str(uuid.uuid4())

    flow = get_flow(st.session_state["oauth_state"])
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes=False,
        prompt="consent",
        state=st.session_state["oauth_state"]
    )

    st.markdown(f"[🔐 Iniciar sesión]({auth_url})")


def exchange_code():
    params = st.experimental_get_query_params()
    if "code" not in params: return

    try:
        code  = params["code"][0]
        state = params["state"][0]

        flow = get_flow(state)
        flow.fetch_token(code=code)

        creds = flow.credentials
        request = grequests.Request()
        userinfo = id_token.verify_oauth2_token(creds.id_token, request, CLIENT_ID)

        st.session_state["logged"]  = True
        st.session_state["profile"] = {
            "email":   userinfo["email"],
            "name":    userinfo["name"],
            "picture": userinfo["picture"]
        }

        st.experimental_set_query_params()
        st.rerun()

    except Exception as e:
        st.error(f"Error: {e}")


def gemini_generate(prompt):
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": float(st.session_state["temperature"]),
            "topP": float(st.session_state["top_p"]),
            "maxOutputTokens": int(st.session_state["max_tokens"])
        }
    }
    try:
        r = requests.post(endpoint, json=payload, timeout=40)
        data = r.json()
        out = ""
        for c in data.get("candidates", []):
            for p in c.get("content", {}).get("parts", []):
                out += p.get("text", "")
        return out.strip()
    except Exception as e:
        return f"Error con Gemini: {e}"


# ------------------------------------------------------------
# Voz Masculina SINCRONIZADA con pausa de video
# ------------------------------------------------------------
def speak_browser(text: str):
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
            const utter = new SpeechSynthesisUtterance(text);

            // Buscar voz masculina en español
            const malePatterns = ["male","man","hombre","miguel","diego","jorge","enrique",
                                  "carlos","juan","sergio","jose","josé","luis"];
            let chosen = null;

            const voices = synth.getVoices();
            for (const v of voices) {{
                const name = (v.name || "").toLowerCase();
                const lang = (v.lang || "").toLowerCase();
                if (lang.startsWith("es") && malePatterns.some(p => name.includes(p))) {{
                    chosen = v;
                    break;
                }}
            }}

            if (!chosen) {{
                chosen = voices.find(v => (v.lang||"").toLowerCase().startsWith("es")) || null;
            }}

            if (chosen) utter.voice = chosen;
            utter.rate = 0.98;
            utter.pitch = 0.48;

            // Pausar video al terminar de hablar
            utter.onend = () => {{
                const vids = parent.document.getElementsByTagName('video');
                for (let v of vids) v.pause();
            }};

            synth.speak(utter);
        }}

        if (synth.getVoices().length === 0) {{
            synth.addEventListener('voiceschanged', speak, {{ once:true }});
        }} else {{
            speak();
        }}
    }})();
    </script>
    """

    components.html(js, height=0)


# ============================================================
# Main
# ============================================================
ensure_defaults()
exchange_code()

if not st.session_state["logged"]:
    login_view()
    st.stop()

st.markdown(header_html(), unsafe_allow_html=True)

conv_col, video_col = st.columns([0.7, 0.3])

# ------------------------------------------------------------
# VIDEO ACTUAL (si existe)
# ------------------------------------------------------------
with video_col:
    video_container = st.empty()
    if st.session_state["current_video"]:
        video_container.markdown(st.session_state["current_video"], unsafe_allow_html=True)

# ------------------------------------------------------------
# Conversación
# ------------------------------------------------------------
with conv_col:

    st.write(f"Bienvenido, **{st.session_state['profile']['name']}** 👋")

    user_msg = st.text_input("Escribe tu pregunta:")

    if st.button("Enviar") and user_msg.strip():

        st.session_state["history"].append({"role": "user", "content": user_msg})

        # ----------------------------------------------------
        # VIDEO ALEATORIO NUEVO
        # ----------------------------------------------------
        try:
            videos = [f for f in os.listdir("assets/videos") if f.lower().endswith(".mp4")]
            if videos:
                choice = random.choice(videos)
                path   = "assets/videos/" + choice

                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")

                html = f"""
                <video width="240" autoplay loop muted playsinline style="border-radius:12px;">
                    <source src="data:video/mp4;base64,{b64}" type="video/mp4">
                </video>
                """

                st.session_state["current_video"] = html
                video_container.markdown(html, unsafe_allow_html=True)

        except Exception as e:
            st.warning(f"No se pudo cargar video: {e}")

        # ----------------------------------------------------
        # RESPUESTA DE GEMINI
        # ----------------------------------------------------
        prompt = f"Eres NICO, asistente institucional de la UMSNH. Responde en español.\n\nUsuario: {user_msg}"

        reply = gemini_generate(prompt)
        st.session_state["history"].append({"role": "assistant", "content": reply})

        st.rerun()

    # Mostrar historial
    for msg in reversed(st.session_state["history"][-15:]):
        if msg["role"] == "user":
            st.chat_message("user").markdown(msg["content"])
        else:
            with st.chat_message("assistant"):
                st.markdown(f"<div class='chat-bubble'>{msg['content']}</div>", unsafe_allow_html=True)
                if st.session_state["voice_on"]:
                    speak_browser(msg["content"])
                break
