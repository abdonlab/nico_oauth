# ============================================================
# NICO OAuth + Gemini 2.0 Flash-Lite + Voz en Navegador
# (Web Search + saludo único + voz grave + icono fijo)
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
# FIX redirección /oauth2callback
# ------------------------------------------------------------
_request_uri = os.environ.get("STREAMLIT_SERVER_REQUEST_URI", "")
if "/oauth2callback" in _request_uri:
    parsed = urllib.parse.urlparse(_request_uri)
    query = urllib.parse.parse_qs(parsed.query)
    st.experimental_set_query_params(**query)
    st.experimental_rerun()

# ------------------------------------------------------------
# Variables de entorno
# ------------------------------------------------------------
load_dotenv()

CLIENT_ID = st.secrets.get("GOOGLE_CLIENT_ID", os.getenv("GOOGLE_CLIENT_ID", ""))
CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET", os.getenv("GOOGLE_CLIENT_SECRET", ""))
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
GEMINI_MODEL = st.secrets.get("GEMINI_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite-001"))

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
    flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=GOOGLE_REDIRECT_URI)
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


# ============================================================
# 🔵 HEADER CON ICONO (NO VIDEO)
# ============================================================

def header_html():
    """Cabecera con icono circular institucional."""
    icon_path = "assets/img/nico_icon.png"

    if os.path.exists(icon_path):
        with open(icon_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        icon_tag = f"""
        <img class="nico-icon" src="data:image/png;base64,{b64}" />
        """
    else:
        icon_tag = '<div class="nico-placeholder"></div>'

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
    .nico-icon {{
        width:56px;
        height:56px;
        border-radius:50%;
        object-fit:cover;
        background:white;
    }}
    .nico-placeholder {{
        width:56px;
        height:56px;
        border-radius:50%;
        background:white;
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
            {icon_tag}
            <div>
                <p class="nico-title">NICO</p>
                <p class="nico-subtitle">Asistente Virtual UMSNH</p>
            </div>
        </div>
    </div>
    """


# ============================================================
# Pantalla de Login
# ============================================================

def login_view():
    st.markdown(header_html(), unsafe_allow_html=True)
    st.info("Inicia sesión con tu cuenta de Google para usar **NICO**.")

    if not CLIENT_ID or not CLIENT_SECRET:
        st.error("Faltan variables OAuth.")
        return

    if "oauth_state" not in st.session_state:
        st.session_state["oauth_state"] = str(uuid.uuid4())

    flow = get_flow(st.session_state["oauth_state"])
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=st.session_state["oauth_state"]
    )

    st.experimental_set_query_params(oauth_state=st.session_state["oauth_state"])
    st.markdown(f"[🔐 Iniciar sesión con Google]({auth_url})")


def exchange_code_for_token():
    params = st.experimental_get_query_params()
    if "code" not in params:
        return

    try:
        code = params["code"][0]
        state = params["state"][0]

        flow = get_flow(state)
        flow.fetch_token(code=code)

        request = grequests.Request()
        idinfo = id_token.verify_oauth2_token(flow.credentials.id_token, request, CLIENT_ID)

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
# Gemini con búsqueda web
# ============================================================

def gemini_generate(prompt, temperature, top_p, max_tokens):
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "topP": top_p,
            "maxOutputTokens": max_tokens,
        },
        "tools": [{"google_search": {}}],
    }

    try:
        r = requests.post(
            endpoint,
            headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
            json=payload,
        )
        r.raise_for_status()
        data = r.json()

        text = ""
        for c in data.get("candidates", []):
            for p in c.get("content", {}).get("parts", []):
                text += p.get("text", "")

        return text.strip()

    except Exception as e:
        return f"⚠️ Error con Gemini: {e}"


# ============================================================
# Voz masculina + sincronización con video
# ============================================================

def speak_browser(text):
    if not text:
        return

    payload = json.dumps(text)

    js = f"""
    <script>
    (function(){{
        const text = {payload};
        const synth = window.speechSynthesis;
        if(!synth) return;

        function speak(){{
            synth.cancel();
            const utter = new SpeechSynthesisUtterance(text);

            const voices = synth.getVoices();
            let chosen = null;

            const prefer = ["rocko","miguel","diego","jorge","pablo","male","hombre"];

            for(const v of voices){{
                if((v.lang||"").toLowerCase().startsWith("es")){
                    if(prefer.some(p => (v.name||"").toLowerCase().includes(p))){
                        chosen = v; break;
                    }
                }
            }}

            if(!chosen){{
                chosen = voices.find(v => (v.lang||"").toLowerCase().startsWith("es"));
            }}

            if(chosen) utter.voice = chosen;

            utter.pitch = 0.65;
            utter.rate = 0.95;

            utter.onstart = () => {{
                const v = parent.document.querySelector('video');
                if(v) v.play();
            }};

            utter.onend = () => {{
                const v = parent.document.querySelector('video');
                if(v) v.pause();
            }};

            synth.speak(utter);
        }}

        if(synth.getVoices().length===0) synth.onvoiceschanged = speak;
        else speak();
    }})();
    </script>
    """

    components.html(js, height=0)


# ============================================================
# App principal
# ============================================================

ensure_session_defaults()
exchange_code_for_token()

if not st.session_state["logged"]:
    login_view()
    st.stop()

# Mostrar cabecera
st.markdown(header_html(), unsafe_allow_html=True)

# Layout
conv_col, video_col = st.columns([0.7, 0.3])

# Columna video (para sincronización)
with video_col:
    video_box = st.empty()
    if st.session_state["current_video"]:
        video_box.markdown(st.session_state["current_video"], unsafe_allow_html=True)

# Columna chat
with conv_col:
    c1, c2, c3 = st.columns([0.15, 0.15, 0.7])

    with c1:
        if st.button("🎙️ Voz ON" if st.session_state["voice_on"] else "🔇 Voz OFF"):
            st.session_state["voice_on"] = not st.session_state["voice_on"]

    with c2:
        if st.button("⚙️ Config"):
            st.session_state["open_cfg"] = True

    with c3:
        st.write(f"👤 {st.session_state['profile'].get('name','')}")

    if st.session_state["open_cfg"]:
        with st.popover("Modelo"):
            st.slider("Temperatura", 0.0, 1.5, key="temperature")
            st.slider("Top-P", 0.0, 1.0, key="top_p")
            st.slider("Máx Tokens", 64, 2048, key="max_tokens", step=32)
            if st.button("Cerrar"):
                st.session_state["open_cfg"] = False

    st.markdown("### 💬 Conversación")

    user_msg = st.text_input("Escribe tu pregunta:")

    if st.button("Enviar") and user_msg.strip():

        st.session_state["history"].append({"role": "user", "content": user_msg})

        # Video aleatorio
        try:
            videos = [f for f in os.listdir("assets/videos") if f.endswith((".mp4",".webm",".ogg",".ogv"))]
            if videos:
                v = random.choice(videos)
                path = os.path.join("assets/videos", v)
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                html_video = f"""
                <video width="240" autoplay muted playsinline loop style="border-radius:12px;">
                    <source src="data:video/mp4;base64,{b64}" type="video/mp4">
                </video>
                """
                st.session_state["current_video"] = html_video
                video_box.markdown(html_video, unsafe_allow_html=True)
        except:
            pass

        # Prompt
        sys_prompt = (
            "Eres NICO, asistente oficial de la UMSNH. "
            "Usa búsqueda web cuando sea necesario y prioriza sitios *.umich.mx."
        )
        full_prompt = f"{sys_prompt}\n\nUsuario: {user_msg}"

        reply = gemini_generate(
            full_prompt,
            st.session_state["temperature"],
            st.session_state["top_p"],
            st.session_state["max_tokens"],
        )

        # Saludo ÚNICO
        if not st.session_state["greeted"]:
            name = st.session_state["profile"].get("name", "usuario")
            saludo = f"Hola {name}, soy NICO — tu asistente virtual de la UMSNH.\n\n"
            reply = saludo + reply
            st.session_state["greeted"] = True

        st.session_state["history"].append({"role": "assistant", "content": reply})
        st.rerun()

    # Mostrar historial
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
                    speak_browser(msg["content"])
            break
