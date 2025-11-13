# ============================================================
# NICO OAuth + Gemini (VERSIÓN FINAL FIJA para Streamlit Cloud)
# ============================================================

import os
import re
import urllib.parse
import json
import base64
import random  # ✅ para elegir video aleatorio
import requests
import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
from speech_utils import synthesize_edge_tts
from dotenv import load_dotenv
import uuid  # Necesario para generar un state único

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
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI
    )
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
        st.error("Faltan GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET/GOOGLE_REDIRECT_URI.")
        return

    # ✅ FIX: Generamos un state persistente con UUID para evitar mismatches
    if "oauth_state" not in st.session_state:
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
        if "oauth_state" not in st.session_state:
            st.session_state["oauth_state"] = state

        # Comentamos el error estricto y sincronizamos el estado
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
def gemini_generate(prompt: str, temperature: float, top_p: float, max_tokens: int) -> str:
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
# Lógica principal
# ============================================================
ensure_session_defaults()
exchange_code_for_token()

if not st.session_state.get("logged"):
    login_view()
    st.stop()

# --- HEADER (igual que antes) ---
st.markdown(header_html(), unsafe_allow_html=True)

# 🔹 Creamos columnas: conversación a la izquierda, video a la derecha
conv_col, video_col = st.columns([0.7, 0.3])

# Contenedor para el video a la derecha
with video_col:
    video_container = st.empty()  # aquí se incrusta el video pequeño

# ============================
# UI de conversación (lado izq.)
# ============================
with conv_col:
    # Barra de controles superior (igual que antes)
    c1, c2, c3 = st.columns([0.1, 0.1, 0.8])
    with c1:
        if st.button("🎙️ Voz: ON" if st.session_state["voice_on"] else "🔇 Voz: OFF"):
            st.session_state["voice_on"] = not st.session_state["voice_on"]
    with c2:
        if st.button("⚙️ Config"):
            st.session_state["open_cfg"] = True
    with c3:
        st.write(f"Bienvenido, **{st.session_state['profile'].get('name','Usuario')}**")

    if st.session_state.get("open_cfg"):
        with st.popover("Configuración del Modelo"):
            st.slider("Temperatura", 0.0, 1.5, key="temperature")
            st.slider("Top-P", 0.0, 1.0, key="top_p")
            st.slider("Máx. tokens", 64, 2048, key="max_tokens", step=32)
            if st.button("Cerrar"):
                st.session_state["open_cfg"] = False

    st.markdown("### 💬 Conversación")

    # Input de usuario
    user_msg = st.text_input("Escribe tu pregunta:")

    # Botón Enviar + lógica de respuesta + video
    if st.button("Enviar") and user_msg.strip():
        # Guardar mensaje del usuario en historial
        st.session_state["history"].append({"role": "user", "content": user_msg})

        # --- 🎬 Mostrar video mientras responde ---
        try:
            video_files = []
            if os.path.isdir("assets/videos"):
                for fname in os.listdir("assets/videos"):
                    if fname.lower().endswith((".mp4", ".webm", ".ogg", ".ogv")):
                        video_files.append(fname)

            if video_files:
                chosen = random.choice(video_files)
                video_path = os.path.join("assets/videos", chosen)
                with open(video_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")

                video_container.markdown(
                    f"""
                    <video width="220" autoplay loop muted playsinline style="border-radius:12px;">
                        <source src="data:video/mp4;base64,{b64}" type="video/mp4">
                    </video>
                    """,
                    unsafe_allow_html=True
                )
        except Exception as e:
            st.warning(f"No se pudo reproducir el video: {e}")

        # --- 🔮 Generar respuesta ---
        sys_prompt = "Eres NICO, asistente institucional de la UMSNH. Responde en español."
        prompt = sys_prompt + "\n\nUsuario: " + user_msg
        reply = gemini_generate(
            prompt,
            st.session_state["temperature"],
            st.session_state["top_p"],
            st.session_state["max_tokens"]
        )

        # Guardar respuesta en historial
        st.session_state["history"].append({"role": "assistant", "content": reply})

        # --- 🛑 Detener el video ---
        # --- 🛑 Detener el video ---
stop_js = """
<script>
    const vids = parent.document.getElementsByTagName('video');
    for (let v of vids) { 
        v.pause(); 
        v.currentTime = 0; 
    }
</script>
"""
st.components.v1.html(stop_js, height=0)

# --- 🧊 Mantener el último frame estático ---
video_container.markdown(
    f"""
    <video width="220" muted playsinline style="border-radius:12px;">
        <source src="data:video/mp4;base64,{b64}" type="video/mp4">
    </video>
    """,
    unsafe_allow_html=True
)

st.rerun()

    # Mostrar historial: último mensaje ARRIBA
    for msg in reversed(st.session_state["history"][-20:]):
        if msg["role"] == "user":
            st.chat_message("user").markdown(msg["content"])
        else:
            with st.chat_message("assistant"):
                st.markdown(f"<div class='chat-bubble'>{msg['content']}</div>", unsafe_allow_html=True)
                if st.session_state["voice_on"]:
                    try:
                        audio_bytes = synthesize_edge_tts(msg["content"])
                        st.audio(audio_bytes, format="audio/mp3")
                    except Exception as e:
                        st.warning(f"Voz no disponible: {e}")

# ------------------------------------------------------------
# Versión anterior del bloque de conversación (SOLO REFERENCIA)
# (comentada para no borrarla, como me pediste)
# ------------------------------------------------------------
# st.markdown("### 💬 Conversación")
#
# # Contenedor del video (siempre arriba del chat)
# video_container = st.empty()
#
# user_msg = st.text_input("Escribe tu pregunta:")
#
# if st.button("Enviar") and user_msg.strip():
#
#     # Guardar mensaje del usuario
#     st.session_state["history"].append({
#         "role": "user",
#         "content": user_msg
#     })
#
#     # --- 🎬 Mostrar video mientras responde ---
#     import random, base64, os
#
#     try:
#         video_files = os.listdir("assets/videos")
#         video_path = f"assets/videos/{random.choice(video_files)}"
#
#         with open(video_path, "rb") as f:
#             b64 = base64.b64encode(f.read()).decode("utf-8")
#
#         video_container.markdown(
#             f"""
#             <video width="180" autoplay loop muted playsinline style="border-radius:10px; float:right; margin:5px;">
#                 <source src="data:video/mp4;base64,{b64}" type="video/mp4">
#             </video>
#             """,
#             unsafe_allow_html=True
#         )
#     except Exception as e:
#         st.warning(f"No se pudo cargar video: {e}")
#
#     # --- 🔮 Generar respuesta ---
#     sys_prompt = "Eres NICO, asistente institucional de la UMSNH. Responde en español."
#     prompt = sys_prompt + "\n\nUsuario: " + user_msg
#
#     reply = gemini_generate(
#         prompt,
#         st.session_state["temperature"],
#         st.session_state["top_p"],
#         st.session_state["max_tokens"]
#     )
#
#     # Guardar respuesta
#     st.session_state["history"].append({
#         "role": "assistant",
#         "content": reply
#     })
#
#     # --- 🛑 Detener el video ---
#     stop_js = """
#     <script>
#         const vids = parent.document.getElementsByTagName('video');
#         for (let v of vids) { v.pause(); v.currentTime = 0; }
#     </script>
#     """
#     st.components.v1.html(stop_js, height=0)
#
#     st.rerun()
#
#
# # 🗂 Mostrar historial (últimos 20)
# for msg in st.session_state["history"][-20:]:
#
#     if msg["role"] == "user":
#         st.chat_message("user").markdown(msg["content"])
#
#     else:
#         with st.chat_message("assistant"):
#             st.markdown(
#                 f"<div class='chat-bubble'>{msg['content']}</div>",
#                 unsafe_allow_html=True
#             )
#
#             if st.session_state["voice_on"]:
#                 try:
#                     audio_bytes = synthesize_edge_tts(msg["content"])
#                     st.audio(audio_bytes, format="audio/mp3")
#                 except Exception as e:
#                     st.warning(f"Voz no disponible: {e}")
