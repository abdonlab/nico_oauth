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
# FIX redirección /oauth2callback
# ------------------------------------------------------------
_request_uri = os.environ.get("STREAMLIT_SERVER_REQUEST_URI", "")
if "/oauth2callback" in _request_uri:
    parsed = urllib.parse.urlparse(_request_uri)
    query = urllib.parse.parse_qs(parsed.query)
    query_clean = {k: v[0] for k, v in query.items()}
    st.query_params.update(query_clean)
    st.rerun()

# ------------------------------------------------------------
# Cargar variables de entorno
# ------------------------------------------------------------
load_dotenv()

CLIENT_ID = st.secrets.get("GOOGLE_CLIENT_ID", os.getenv("GOOGLE_CLIENT_ID", ""))
CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET", os.getenv("GOOGLE_CLIENT_SECRET", ""))
GOOGLE_REDIRECT_URI = st.secrets.get("GOOGLE_REDIRECT_URI", os.getenv("GOOGLE_REDIRECT_URI", "https://nicooapp-umsnh.streamlit.app/"))

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))

# 🚀 CAMBIO CRÍTICO: Modelo 'gemini-2.5-flash' para que funcione la Búsqueda Web
GEMINI_MODEL = st.secrets.get("GEMINI_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))

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
    st.session_state.setdefault("is_exchanging_token", False)


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


def login_view():
    st.markdown(header_html(), unsafe_allow_html=True)
    st.info("Inicia sesión con tu cuenta de Google para usar **NICO**.")

    if not CLIENT_ID or not CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
        st.error("Faltan variables de configuración OAuth.")
        return

    if "oauth_state" not in st.session_state:
        st.session_state["oauth_state"] = str(uuid.uuid4())

    state_key = st.session_state["oauth_state"]
    flow = get_flow(state=state_key)

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes=False,
        prompt="consent",
        state=state_key,
    )

    st.query_params["oauth_state"] = state_key
    st.markdown(f"""
    <a href="{auth_url}" target="_self" style="
        display: inline-block;
        background-color: #4285F4; color: white; padding: 12px 24px;
        text-decoration: none; border-radius: 6px; font-family: sans-serif;
        font-weight: bold; font-size: 16px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2); margin-top: 10px;
    ">
        🔐 Iniciar sesión con Google
    </a>
    """, unsafe_allow_html=True)


def exchange_code_for_token():
    try:
        params = st.query_params
        code = params.get("code")
        state = params.get("state")
    except:
        return

    if not code or not state:
        return

    if st.session_state.get("is_exchanging_token"):
        return

    st.session_state["is_exchanging_token"] = True

    try:
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
            "picture": idinfo.get("picture"),
        }
        
        st.session_state["is_exchanging_token"] = False
        st.query_params.clear()
        st.rerun() 

    except Exception as e:
        st.error(f"Error al autenticar: {e}")
        st.session_state["is_exchanging_token"] = False
        st.query_params.clear()
        st.rerun()


# ============================================================
# Gemini (Modelo 2.5 Flash para Búsqueda Web)
# ============================================================
def gemini_generate(prompt: str, temperature: float, top_p: float, max_tokens: int) -> str:
    # Usamos el modelo cargado (debe ser gemini-2.5-flash)
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": float(temperature),
            "topP": float(top_p),
            "maxOutputTokens": int(max_tokens),
        },
        "tools": [{"google_search": {}}], # Activa la búsqueda web
    }

    try:
        r = requests.post(endpoint, headers=headers, json=payload, timeout=40)
        r.raise_for_status()
        data = r.json()
        text = ""
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                text += part.get("text", "")
        return text.strip() or "No obtuve respuesta del modelo."
    except Exception as e:
        return f"⚠️ Error con Gemini: {e}"


def speak_browser(text: str):
    """Voz del Asistente (TTS)."""
    if not text: return
    payload = json.dumps(text)

    js_code = f"""
    <script>
    (function() {{
        const text = {payload};
        const synth = window.speechSynthesis;
        if (!synth) return;

        function findVideo() {{
            const v = parent.document.querySelector('video');
            return v;
        }}

        function speak() {{
            synth.cancel();
            const utter = new SpeechSynthesisUtterance(text);
            const voices = synth.getVoices() || [];
            let chosen = null;
            const preferNames = ["miguel", "diego", "jorge", "pablo", "male", "hombre"];
            for (const v of voices) {{
                const name = (v.name || "").toLowerCase();
                const lang = (v.lang || "").toLowerCase();
                if (lang.startsWith("es")) {{
                    for (const pref of preferNames) {{
                        if (name.includes(pref)) {{ chosen = v; break; }}
                    }}
                }}
                if (chosen) break;
            }}
            if (!chosen) {{
                for (const v of voices) {{
                    if (v.lang.toLowerCase().startsWith("es")) {{ chosen = v; break; }}
                }}
            }}
            if (chosen) utter.voice = chosen;
            utter.rate = 0.95;
            utter.pitch = 0.65;
            utter.onstart = () => {{ const v = findVideo(); if (v) v.play(); }};
            utter.onend = () => {{ const v = findVideo(); if (v) v.pause(); }};
            synth.speak(utter);
        }}

        if (synth.getVoices().length === 0) {{
            synth.addEventListener('voiceschanged', function handler() {{
                synth.removeEventListener('voiceschanged', handler);
                speak();
            }});
        }} else {{
            speak();
        }}
    }})();
    </script>
    """
    components.html(js_code, height=0)


def listen_browser():
    """
    Escucha al usuario (STT) y escribe en el input.
    """
    js_code = """
    <script>
    (function() {
        const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
        
        if (!recognition) {
            alert('❌ Tu navegador no soporta reconocimiento de voz.');
            return;
        }

        recognition.lang = 'es-MX';
        recognition.interimResults = false;
        recognition.maxAlternatives = 1;
        
        const inputField = parent.document.querySelector('input[data-testid="stTextInput"]');
        const speakButton = parent.document.querySelector('.stButton button[title*="Hacer clic"]');

        if (speakButton) {
            speakButton.innerText = '🔴 Escuchando...';
            speakButton.style.backgroundColor = '#FF4B4B';
            speakButton.style.color = '#FFFFFF';
        }

        recognition.onresult = function(event) {
            const transcript = event.results[0][0].transcript;
            
            if (inputField) {
                inputField.value = transcript;
                inputField.dispatchEvent(new Event('input', { bubbles: true }));
                // Disparar envío automático
                inputField.dispatchEvent(new Event('change', { bubbles: true })); 
            }
        };

        recognition.onspeechend = function() { recognition.stop(); };

        recognition.onend = function() {
            if (speakButton) {
                speakButton.innerText = '🎙️ Hablar';
                speakButton.style.backgroundColor = '';
                speakButton.style.color = '';
            }
        };

        recognition.start();
    })();
    </script>
    """
    components.html(js_code, height=0)


# ============================================================
# Lógica Principal de Chat (Optimizada para evitar duplicados)
# ============================================================

def process_chat_message():
    """
    Procesa el mensaje del usuario, llama a la API y actualiza el historial.
    Se asegura de limpiar el input y evita dobles ejecuciones.
    """
    user_msg = st.session_state["input_val"]
    
    if not user_msg.strip():
        return

    # 1. Guardar mensaje de usuario
    st.session_state["history"].append({"role": "user", "content": user_msg})

    # 2. Limpiar input inmediatamente
    st.session_state["input_val"] = ""

    # 3. Video Aleatorio
    try:
        video_files = [f for f in os.listdir("assets/videos") if f.lower().endswith((".mp4", ".webm"))]
        if video_files:
            chosen = random.choice(video_files)
            video_path = os.path.join("assets/videos", chosen)
            with open(video_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            
            html_video = f"""
            <video width="220" loop muted playsinline style="border-radius:12px;">
                <source src="data:video/mp4;base64,{b64}" type="video/mp4">
            </video>
            """
            st.session_state["current_video"] = html_video
    except Exception as e:
        pass # Fallo silencioso del video para no interrumpir

    # 4. Prompt
    full_name = st.session_state['profile'].get('name', 'Usuario')
    first_name = full_name.split(' ')[0] if full_name else 'Amigo'
    
    sys_prompt = (
        "Eres NICO, asistente institucional de la Universidad Michoacana de San Nicolás de Hidalgo (UMSNH). "
        f"El usuario se llama {first_name}. "
        "Tu objetivo es informar de manera precisa, eficiente y alegre. "
        "**REGLA DE ORO:** Usa Google Search para CUALQUIER dato sobre noticias, convocatorias, fechas o autoridades actuales (post-2023). "
        "NO uses negritas (**texto**), ni markdown, ni listas con viñetas. Escribe en párrafos naturales. "
        "No saludes al inicio de cada respuesta, ve directo al grano. "
        "Prioriza fuentes oficiales como *.umich.mx. "
    )

    full_prompt = sys_prompt + "\n\n--- HISTORIAL ---\n"
    # Últimos 5 mensajes para contexto
    for msg in st.session_state["history"][-5:]: 
        role = "Asistente" if msg["role"] == "assistant" else "Usuario"
        content = msg["content"]
        if not st.session_state["greeted"] and content.startswith(f"¡Hola {first_name}!"):
            continue 
        full_prompt += f"{role}: {content}\n"
    
    full_prompt += f"\n--- FIN HISTORIAL ---\nUsuario: {user_msg}"

    # 5. Generar Respuesta (con Spinner)
    with st.spinner("Buscando y generando respuesta..."):
        reply_raw = gemini_generate(
            full_prompt,
            st.session_state["temperature"],
            st.session_state["top_p"],
            st.session_state["max_tokens"],
        )
    
    # 6. Saludo inicial si aplica
    if not st.session_state["greeted"]:
        saludo = f"¡Hola {first_name}! Soy NICO, tu asistente virtual.\n\n"
        reply = saludo + reply_raw
        st.session_state["greeted"] = True
    else:
        reply = reply_raw

    # 7. Guardar y Recargar
    st.session_state["history"].append({"role": "assistant", "content": reply})
    st.rerun()


# ============================================================
# Ejecución Principal
# ============================================================

ensure_session_defaults()
exchange_code_for_token()

if not st.session_state.get("logged"):
    login_view()
    st.stop()

# Cabecera
st.markdown(header_html(), unsafe_allow_html=True)

# Layout
conv_col, video_col = st.columns([0.7, 0.3])

with video_col:
    video_container = st.empty()
    if st.session_state["current_video"]:
        video_container.markdown(st.session_state["current_video"], unsafe_allow_html=True)
    elif not st.session_state["current_video"]:
        # Intento inicial de cargar video
        try:
            video_files = [f for f in os.listdir("assets/videos") if f.lower().endswith((".mp4", ".webm"))]
            if video_files:
                chosen = random.choice(video_files)
                with open(os.path.join("assets/videos", chosen), "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                st.session_state["current_video"] = f"""
                <video width="220" loop muted playsinline style="border-radius:12px;">
                    <source src="data:video/mp4;base64,{b64}" type="video/mp4">
                </video>
                """
                video_container.markdown(st.session_state["current_video"], unsafe_allow_html=True)
        except: pass

with conv_col:
    # Controles Superiores: Voz (TTS), Config, Micrófono (STT), Usuario
    c1, c2, c3, c4 = st.columns([0.15, 0.15, 0.15, 0.55]) 
    with c1:
        if st.button("🎙️ Voz: " + ("ON" if st.session_state["voice_on"] else "OFF"), key="tts_btn"):
            st.session_state["voice_on"] = not st.session_state["voice_on"]
            st.rerun() 
    with c2:
        if st.button("⚙️ Config", key="cfg_btn"):
            st.session_state["open_cfg"] = True
    
    # BOTÓN DE ESCUCHAR (Micrófono)
    with c3:
        # El título ayuda al JS a encontrar el botón
        if st.button("🎙️ Hablar", help="Hacer clic y empezar a hablar", key="stt_btn"):
            listen_browser()
            
    with c4:
        st.write(f"Bienvenido, **{st.session_state['profile'].get('name', '').split()[0]}**")

    if st.session_state.get("open_cfg"):
        with st.expander("Configuración"):
            st.slider("Temperatura", 0.0, 1.5, key="temperature")
            st.slider("Top-P", 0.0, 1.0, key="top_p")
            if st.button("Cerrar Config"):
                st.session_state["open_cfg"] = False
                st.rerun()

    st.markdown("### 💬 Conversación")

    # Función para limpiar el input manualmente
    def action_clear():
        st.session_state["input_val"] = ""
        st.rerun() 

    # Input de texto (vinculado a la función de procesamiento)
    st.text_input(
        "Escribe tu pregunta:", 
        key="input_val", 
        on_change=process_chat_message
    )

    # Botones de acción
    btn_c1, btn_c2, _ = st.columns([0.15, 0.15, 0.7])
    with btn_c1:
        st.button("Enviar 🚀", on_click=process_chat_message) 
    with btn_c2:
        st.button("Borrar 🗑️", on_click=action_clear)

    # Mostrar Historial
    for i, msg in enumerate(st.session_state["history"]):
        if msg["role"] == "user":
            st.chat_message("user").markdown(msg["content"])
        else:
            with st.chat_message("assistant"):
                st.markdown(f"<div class='chat-bubble'>{msg['content']}</div>", unsafe_allow_html=True)
                
                # Hablar solo el último mensaje del asistente
                if i == len(st.session_state["history"]) - 1 and st.session_state["voice_on"]:
                    time.sleep(0.3) 
                    speak_browser(msg["content"])
