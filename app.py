# ============================================================
# NICO OAuth + Gemini 2.0 Flash-Lite + Voz en Navegador
# (CORREGIDO: st.rerun y st.query_params para Streamlit nuevo)
# ============================================================

import os
import urllib.parse
import json
import base64
import random
import requests
import uuid
import time 

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
# FIX redirección /oauth2callback (Actualizado para st.query_params)
# ------------------------------------------------------------
_request_uri = os.environ.get("STREAMLIT_SERVER_REQUEST_URI", "")
if "/oauth2callback" in _request_uri:
    parsed = urllib.parse.urlparse(_request_uri)
    query = urllib.parse.parse_qs(parsed.query)
    # Convertir valores de lista a string
    query_clean = {k: v[0] for k, v in query.items()}
    st.query_params.update(query_clean)
    st.rerun()

# ------------------------------------------------------------
# Cargar variables de entorno
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
GEMINI_MODEL = st.secrets.get("GEMINI_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite-preview-02-05"))

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
    st.session_state.setdefault("greeted", False)
    st.session_state.setdefault("input_val", "")
    st.session_state.setdefault("trigger_run", False)

# ============================================================
# 🔵 HEADER NUEVO (ÚNICO CAMBIO QUE ME PEDISTE)
# ============================================================

def header_html():
    """Cabecera visual."""
    video_path = "assets/videos/nico_header_video.mp4"
    video_tag = '<div class="nico-placeholder">🦊</div>'
    
    if os.path.exists(video_path):
        with open(video_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        video_tag = f"""
        <video class="nico-video" autoplay loop muted playsinline>
            <source src="data:video/mp4;base64,{b64}" type="video/mp4">
        </video>
        """

    return f"""
    <style>
    .nico-header {{
        background: linear-gradient(90deg, #0f2347 0%, #1a3b6e 100%);
        color: #fff;
        padding: 16px 24px;
        border-radius: 12px;
        margin-bottom: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }}
    .nico-wrap {{ display: flex; align-items: center; gap: 16px; }}
    .nico-video, .nico-placeholder {{
        width: 60px; height: 60px; border-radius: 50%;
        background: #fff; object-fit: cover; border: 2px solid #ffd700;
        display: flex; align-items: center; justify-content: center; font-size: 30px;
    }}
    .nico-title {{ font-size: 24px; font-weight: 800; margin: 0; }}
    .nico-subtitle {{ margin: 0; font-size: 16px; opacity: 0.8; font-weight: 300; }}
    .chat-bubble {{
        background: #f0f2f6; border-radius: 12px; padding: 16px; margin-top: 8px;
        color: #31333F; border-left: 4px solid #0f2347;
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

# ============================================================
# Login View
# ============================================================

def login_view():
    st.markdown(header_html(), unsafe_allow_html=True)
    st.info("🔒 Acceso restringido. Inicia sesión con tu cuenta institucional o Google.")

    # ⭐ FIX: evitar KeyError por oauth_state
    if "oauth_state" not in st.session_state:
        st.session_state["oauth_state"] = str(uuid.uuid4())

    state_key = st.session_state["oauth_state"]
    flow = get_flow(state=state_key)
    auth_url, _ = flow.authorization_url(prompt="consent")

    st.markdown(f"""
        <a href="{auth_url}" target="_self" style="
            display: inline-block; text-decoration: none; color: white;
            background-color: #4285F4; padding: 10px 20px; border-radius: 5px;
            font-weight: bold; font-family: sans-serif;">
            🔐 Iniciar sesión con Google
        </a>
    """, unsafe_allow_html=True)

def exchange_code_for_token():
    """Intercambiar el código OAuth por tokens y obtener perfil."""
    try:
        params = st.query_params
        code = params.get("code")
        state = params.get("state")
    except:
        return

    if not code or not state:
        return

    try:
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

        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Error al autenticar: {e}")

# ============================================================
# Gemini 2.0 con búsqueda web
# ============================================================

def gemini_generate(prompt: str, temperature: float, top_p: float, max_tokens: int) -> str:
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    headers = { "Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY }
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
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                text += part.get("text", "")
        return text.strip() or "No obtuve respuesta."
    except Exception as e:
        return f"⚠️ Error con Gemini: {e}"


# ============================================================
# Web Speech API sync con video
# ============================================================

def speak_browser(text: str):
    if not text: return
    payload = json.dumps(text)

    js_code = f"""
    <script>
    (function() {{
        const text = {payload};
        const synth = window.speechSynthesis;
        if (!synth) return;

        function findVideo() {{
            return parent.document.querySelector('video');
        }}

        function speak() {{
            synth.cancel();
            const utter = new SpeechSynthesisUtterance(text);
            const voices = synth.getVoices() || [];
            let chosen = null;
            
            const pref = ["rocko","miguel","diego","jorge","male","hombre"];
            for (const v of voices) {{
                if (v.lang.toLowerCase().startsWith("es")) {{
                    for (const p of pref)
                        if ((v.name||"").toLowerCase().includes(p)) chosen = v;
                }}
            }}
            if (!chosen)
                for (const v of voices)
                    if (v.lang.toLowerCase().startsWith("es")) chosen = v;

            if (chosen) utter.voice = chosen;

            utter.rate = 0.95;
            utter.pitch = 0.65;

            utter.onstart = () => {{ const v=findVideo(); if(v) v.play(); }};
            utter.onend   = () => {{ const v=findVideo(); if(v) v.pause(); }};

            synth.speak(utter);
        }}

        if (synth.getVoices().length === 0)
            synth.addEventListener('voiceschanged', ()=>speak());
        else speak();
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
    
    if not st.session_state["current_video"]:
        try:
            video_files = [f for f in os.listdir("assets/videos") if f.lower().endswith((".mp4", ".webm"))]
            if video_files:
                chosen = random.choice(video_files)
                video_path = os.path.join("assets/videos", chosen)
                with open(video_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                st.session_state["current_video"] = f"""
                <video width="220" autoplay loop muted playsinline style="border-radius:12px;">
                    <source src="data:video/mp4;base64,{b64}" type="video/mp4">
                </video>
                """
        except: pass
            
    if st.session_state["current_video"]:
        video_container.markdown(st.session_state["current_video"], unsafe_allow_html=True)

with conv_col:
    c1, c2, c3 = st.columns([0.15, 0.15, 0.7])
    with c1:
        if st.button("🎙️ Voz: " + ("ON" if st.session_state["voice_on"] else "OFF")):
            st.session_state["voice_on"] = not st.session_state["voice_on"]
            st.rerun()
    with c2:
        if st.button("⚙️ Config"):
            st.session_state["open_cfg"] = True
    with c3:
        st.write(f"Bienvenido, **{st.session_state['profile'].get('name', '')}**")

    if st.session_state["open_cfg"]:
        with st.expander("Configuración del Modelo"):
            st.slider("Temperatura", 0.0, 1.5, key="temperature")
            st.slider("Top-P", 0.0, 1.0, key="top_p")
            st.slider("Máx. tokens", 64, 2048, key="max_tokens", step=32)
            if st.button("Cerrar Config"):
                st.session_state["open_cfg"] = False
                st.rerun()

    st.markdown("### 💬 Conversación")

    def action_submit():
        if st.session_state["input_val"].strip():
            st.session_state["trigger_run"] = True

    def action_clear():
        st.session_state["input_val"] = ""
        st.session_state["trigger_run"] = False

    st.text_input(
        "Escribe tu pregunta:",
        key="input_val",
        on_change=action_submit
    )

    bc1, bc2, _ = st.columns([0.15,0.15,0.7])
    with bc1:
        st.button("Enviar 🚀", on_click=action_submit)
    with bc2:
        st.button("Borrar 🗑️", on_click=action_clear)

    if st.session_state["trigger_run"]:
        user_msg = st.session_state["input_val"]
        st.session_state["history"].append({"role":"user","content":user_msg})

        try:
            video_files = [f for f in os.listdir("assets/videos") if f.lower().endswith((".mp4", ".webm"))]
            if video_files:
                chosen = random.choice(video_files)
                video_path = os.path.join("assets/videos", chosen)
                with open(video_path,"rb") as f: 
                    b64 = base64.b64encode(f.read()).decode()
                
                html_video = f"""
                <video width="220" autoplay loop muted playsinline style="border-radius:12px;">
                    <source src="data:video/mp4;base64,{b64}" type="video/mp4">
                </video>
                """
                st.session_state["current_video"] = html_video
                video_container.markdown(html_video, unsafe_allow_html=True)
        except Exception as e:
            st.warning(f"Video error: {e}")

        full_name = st.session_state['profile'].get('name','Usuario')
        first_name = full_name.split(' ')[0] if full_name else 'Amigo'

        # ⭐ TU PROMPT ORIGINAL (no tocado)
        sys_prompt = (
            "Eres NICO, asistente institucional de la Universidad Michoacana de San Nicolás de Hidalgo (UMSNH). "
            f"El usuario se llama {first_name}. "
            "La rectora de la Universidad Michoacana de San Nicolás de Hidalgo (UMSNH) es Yarabí Ávila González. Fue designada para este cargo por el periodo 2023-2027."
            "NO uses negritas, NO uses Markdown, NO uses símbolos como **, *, _, #, ~~, etc. "
            "NO generes listas con guiones. "        
            "Responde siempre en español o Ingles o purepechade segun te lo soliciten de forma clara, breve y amable. "
            "Usa su nombre ocasionalmente en la conversación para que suene natural, pero no en cada frase.\n"
            "IMPORTANTE: No uses negritas (*texto*) ni formato markdown pesado en tus respuestas. Escribe solo texto plano.\n\n"
            "Usa la búsqueda web para información actualizada. Prioriza sitios *.umich.mx."
            "- https://www.umich.mx\n" 
            "para ultimas noticias busca en https://www.gacetanicolaita.umich.mx/"
            "para nombres de funcionarios busca en https://umich.mx/unidades-administrativas/"    
            "-https://www.gacetanicolaita.umich.mx/n"
            "-https://umich.mx/unidades-administrativas/n"
            "- https://www.dce.umich.mx\n"
            "- https://siia.umich.mx\n"
        )

        full_prompt = f"{sys_prompt}\n\nUsuario: {user_msg}"

        reply = gemini_generate(
            full_prompt,
            st.session_state["temperature"],
            st.session_state["top_p"],
            st.session_state["max_tokens"],
        )

        if not st.session_state["greeted"]:
            saludo = f"¡Hola {first_name}! Soy NICO, tu asistente virtual.\n\n"
            reply = saludo + reply
            st.session_state["greeted"] = True

        st.session_state["history"].append({"role":"assistant","content":reply})
        
        st.session_state["trigger_run"] = False
        st.rerun()

    for msg in reversed(st.session_state["history"][-20:]):
        if msg["role"] == "user":
            st.chat_message("user").markdown(msg["content"])
        else:
            with st.chat_message("assistant"):
                st.markdown(f"<div class='chat-bubble'>{msg['content']}</div>", unsafe_allow_html=True)
                if st.session_state["voice_on"]:
                    speak_browser(msg["content"])
            break
