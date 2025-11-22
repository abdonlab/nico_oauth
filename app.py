# ============================================================
# NICO: Asistente Virtual UMSNH (Full Version)
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
# 1. Configuración inicial de Streamlit
# ------------------------------------------------------------
st.set_page_config(
    page_title="NICO | Asistente Virtual UMSNH",
    page_icon="🦊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ------------------------------------------------------------
# 2. Cargar variables de entorno
# ------------------------------------------------------------
load_dotenv()

CLIENT_ID = st.secrets.get("GOOGLE_CLIENT_ID", os.getenv("GOOGLE_CLIENT_ID", ""))
CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET", os.getenv("GOOGLE_CLIENT_SECRET", ""))
GOOGLE_REDIRECT_URI = st.secrets.get(
    "GOOGLE_REDIRECT_URI",
    os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8501/") # Cambiar en producción
)

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
GEMINI_MODEL = "gemini-2.0-flash-lite-preview-02-05"

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# ------------------------------------------------------------
# 3. Gestión de Sesión (Estado)
# ------------------------------------------------------------
def ensure_session_defaults():
    defaults = {
        "logged": False,
        "profile": {},
        "history": [],
        "voice_on": True,
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 512,
        "current_video_html": None,
        "last_spoken_id": None,
        "greeted": False,
        "oauth_state": str(uuid.uuid4()),
        "input_val": "",       # Texto del usuario
        "trigger_run": False   # Bandera para ejecutar la IA
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

ensure_session_defaults()

# ------------------------------------------------------------
# 4. Funciones OAuth (Login)
# ------------------------------------------------------------
def get_flow(state=None):
    client_config = {
        "web": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(
        client_config, scopes=SCOPES, redirect_uri=GOOGLE_REDIRECT_URI
    )
    if state:
        flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow

def check_auth_callback():
    try:
        # Soporte para nuevas versiones de Streamlit
        query_params = st.query_params
        code = query_params.get("code")
        state = query_params.get("state")
    except:
        return

    if code and state:
        try:
            flow = get_flow(state=state)
            flow.fetch_token(code=code)
            creds = flow.credentials
            idinfo = id_token.verify_oauth2_token(creds.id_token, grequests.Request(), CLIENT_ID)
            
            st.session_state["logged"] = True
            st.session_state["profile"] = {
                "email": idinfo.get("email"),
                "name": idinfo.get("name"),
                "picture": idinfo.get("picture"),
            }
            st.query_params.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Error de autenticación: {e}")

# ------------------------------------------------------------
# 5. Componentes UI (Header y Login)
# ------------------------------------------------------------
def header_html():
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
        color: #fff; padding: 16px 24px; border-radius: 12px;
        margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
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

def login_view():
    st.markdown(header_html(), unsafe_allow_html=True)
    st.info("🔒 Acceso restringido. Inicia sesión para continuar.")
    state_key = st.session_state["oauth_state"]
    flow = get_flow(state=state_key)
    auth_url, _ = flow.authorization_url(prompt="consent")
    st.markdown(f'<a href="{auth_url}" target="_self" style="background-color:#4285F4;color:white;padding:10px 20px;text-decoration:none;border-radius:5px;font-weight:bold;">🔐 Iniciar sesión con Google</a>', unsafe_allow_html=True)

# ------------------------------------------------------------
# 6. Lógica Core (Gemini + Voz)
# ------------------------------------------------------------
def gemini_generate(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": st.session_state["temperature"],
            "topP": st.session_state["top_p"],
            "maxOutputTokens": st.session_state["max_tokens"],
        },
        "tools": [{"google_search": {}}]
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        text_parts = []
        if "candidates" in data:
            for cand in data["candidates"]:
                if "content" in cand and "parts" in cand["content"]:
                    for part in cand["content"]["parts"]:
                        text_parts.append(part.get("text", ""))
        return "".join(text_parts).strip() or "No obtuve respuesta."
    except Exception as e:
        return f"⚠️ Error: {str(e)}"

def speak_and_sync(text, unique_id):
    if st.session_state["last_spoken_id"] == unique_id:
        return
    st.session_state["last_spoken_id"] = unique_id
    safe_text = json.dumps(text)
    js_code = f"""
    <script>
    (function() {{
        const text = {safe_text};
        const synth = window.speechSynthesis;
        if (!synth) return;
        function findVideo() {{ return parent.document.getElementById('nico-video-active'); }}
        function speak() {{
            synth.cancel();
            const utter = new SpeechSynthesisUtterance(text);
            const voices = synth.getVoices();
            let chosen = voices.find(v => v.lang.startsWith('es') && (v.name.toLowerCase().includes('rocko') || v.name.toLowerCase().includes('male')));
            if (!chosen) chosen = voices.find(v => v.lang.startsWith('es'));
            if (chosen) utter.voice = chosen;
            utter.pitch = 0.7; utter.rate = 1.0;
            utter.onstart = () => {{ const vid = findVideo(); if (vid) vid.play(); }};
            utter.onend = () => {{ const vid = findVideo(); if (vid) {{ vid.pause(); vid.currentTime = 0; }} }};
            synth.speak(utter);
        }}
        if (synth.getVoices().length === 0) {{ synth.addEventListener('voiceschanged', speak); }} else {{ speak(); }}
    }})();
    </script>
    """
    components.html(js_code, height=0)

# ------------------------------------------------------------
# 7. Ejecución Principal
# ------------------------------------------------------------
check_auth_callback()

if not st.session_state["logged"]:
    login_view()
    st.stop()

st.markdown(header_html(), unsafe_allow_html=True)
col_chat, col_video = st.columns([0.7, 0.3])

# --- COLUMNA DERECHA (VIDEO) ---
with col_video:
    video_placeholder = st.empty()
    if not st.session_state["current_video_html"]:
        try:
            vid_dir = "assets/videos"
            if os.path.exists(vid_dir):
                files = [f for f in os.listdir(vid_dir) if f.endswith(('.mp4','.webm'))]
                if files:
                    initial_vid = random.choice(files)
                    with open(os.path.join(vid_dir, initial_vid), "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("utf-8")
                    st.session_state["current_video_html"] = f"""
                    <video id="nico-video-active" width="100%" loop muted playsinline style="border-radius:12px; box-shadow: 0 4px 12px rgba(0,0,0,0.2);">
                        <source src="data:video/mp4;base64,{b64}" type="video/mp4">
                    </video>
                    """
        except:
            st.session_state["current_video_html"] = "Video no disponible"

    if st.session_state["current_video_html"]:
        video_placeholder.markdown(st.session_state["current_video_html"], unsafe_allow_html=True)

    st.write("---")
    st.write(f"👤 **{st.session_state['profile'].get('name')}**")
    if st.button("🎙️ Voz: " + ("ON" if st.session_state["voice_on"] else "OFF")):
        st.session_state["voice_on"] = not st.session_state["voice_on"]
        st.rerun()
    if st.button("🚪 Salir"):
        st.session_state.clear()
        st.rerun()

# --- COLUMNA IZQUIERDA (CHAT) ---
with col_chat:
    st.write("### 💬 Conversación")

    # Callbacks
    def action_submit():
        if st.session_state["input_val"].strip():
            st.session_state["trigger_run"] = True
    
    def action_clear():
        st.session_state["input_val"] = ""
        st.session_state["trigger_run"] = False

    # Input de texto con Enter habilitado
    st.text_input("Escribe aquí:", key="input_val", on_change=action_submit)

    # Botones
    c1, c2, c3 = st.columns([0.15, 0.15, 0.7])
    with c1: st.button("Enviar 🚀", on_click=action_submit)
    with c2: st.button("Borrar 🗑️", on_click=action_clear)

    # Procesamiento
    if st.session_state["trigger_run"]:
        user_msg = st.session_state["input_val"]
        st.session_state["history"].append({"role": "user", "content": user_msg})
        
        # Lógica video aleatorio
        try:
            vid_dir = "assets/videos"
            if os.path.exists(vid_dir):
                files = [f for f in os.listdir(vid_dir) if f.endswith(('.mp4','.webm')) and "header" not in f]
                if files:
                    chosen = random.choice(files)
                    with open(os.path.join(vid_dir, chosen), "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("utf-8")
                    st.session_state["current_video_html"] = f"""
                    <video id="nico-video-active" width="100%" loop muted playsinline style="border-radius:12px; box-shadow: 0 4px 12px rgba(0,0,0,0.2);">
                        <source src="data:video/mp4;base64,{b64}" type="video/mp4">
                    </video>
                    """
        except: pass

        # Lógica Gemini
        sys_prompt = "Eres NICO, asistente oficial de la UMSNH. Responde en español, claro y breve."
        full_prompt = f"{sys_prompt}\n\nHistorial: {st.session_state['history'][-3:]}\n\nUsuario: {user_msg}"
        
        with st.spinner("Pensando..."):
            reply = gemini_generate(full_prompt)

        if not st.session_state["greeted"]:
            name = st.session_state["profile"].get("name", "").split(" ")[0]
            reply = f"¡Hola {name}! " + reply
            st.session_state["greeted"] = True

        st.session_state["history"].append({"role": "assistant", "content": reply})
        st.session_state["trigger_run"] = False # Reset trigger
        st.rerun()

    # Historial
    for i, msg in enumerate(st.session_state["history"]):
        if msg["role"] == "user":
            st.chat_message("user").write(msg["content"])
        else:
            with st.chat_message("assistant", avatar="🦊"):
                st.markdown(f"<div class='chat-bubble'>{msg['content']}</div>", unsafe_allow_html=True)
                if i == len(st.session_state["history"]) - 1 and st.session_state["voice_on"]:
                    speak_and_sync(msg['content'], f"{len(msg['content'])}-{str(time.time())[:5]}")
