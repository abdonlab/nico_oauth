# ============================================================
# NICO OAuth + Gemini 2.0 Flash-Lite + Web Search UMSNH
# Voz en Navegador (más grave, masculina, neutra)
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
    page_icon="🤖",
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
# Cargar variables de entorno
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
# FUNCIONES AUXILIARES
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
    st.session_state.setdefault("oauth_credentials", None)
    st.session_state.setdefault("open_cfg", False)


# ------------------------------------------------------------
# TOKEN OAUTH PARA DISCOVERY ENGINE
# ------------------------------------------------------------
def get_access_token():
    """Devuelve el token OAuth actual para llamadas web."""
    creds = st.session_state.get("oauth_credentials", None)
    if creds:
        return creds.token
    return None


# ------------------------------------------------------------
# AUTENTICACIÓN OAUTH
# ------------------------------------------------------------
def login_view():
    st.markdown(header_html(), unsafe_allow_html=True)
    st.info("Inicia sesión con Google para usar NICO.")

    if not CLIENT_ID or not CLIENT_SECRET:
        st.error("Faltan claves OAuth.")
        return

    if "oauth_state" not in st.session_state:
        st.session_state["oauth_state"] = str(uuid.uuid4())

    flow = get_flow(state=st.session_state["oauth_state"])
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes=False,
        prompt="consent",
        state=st.session_state["oauth_state"],
    )

    st.markdown(f"[🔐 Iniciar sesión con Google]({auth_url})")


def exchange_code_for_token():
    params = st.experimental_get_query_params()
    if "code" not in params:
        return

    code = params["code"][0]
    state = params["state"][0]

    flow = get_flow(state)
    try:
        flow.fetch_token(code=code)
        creds = flow.credentials

        st.session_state["oauth_credentials"] = creds
        req = grequests.Request()
        userinfo = id_token.verify_oauth2_token(creds.id_token, req, CLIENT_ID)

        st.session_state["logged"] = True
        st.session_state["profile"] = {
            "name": userinfo.get("name"),
            "email": userinfo.get("email"),
            "picture": userinfo.get("picture"),
        }

        st.experimental_set_query_params()
        st.rerun()

    except Exception as e:
        st.error(f"Error OAuth: {e}")


# ------------------------------------------------------------
# CABECERA HTML
# ------------------------------------------------------------
def header_html():
    return """
    <div style="background:#0f2347;color:white;padding:16px;border-radius:12px;">
        <h2 style="margin:0;">NICO — Asistente Virtual UMSNH</h2>
        <p style="margin:0;opacity:.9;">Búsqueda oficial • Respuestas inteligentes</p>
    </div>
    """

# ------------------------------------------------------------
# GEMINI REQUEST
# ------------------------------------------------------------
def gemini_generate(prompt: str, temperature: float, top_p: float, max_tokens: int):
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "topP": top_p,
            "maxOutputTokens": max_tokens,
        },
    }

    try:
        r = requests.post(endpoint, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        text = ""
        for c in data.get("candidates", []):
            for p in c.get("content", {}).get("parts", []):
                text += p.get("text", "")
        return text
    except Exception as e:
        return f"⚠️ Error con Gemini: {e}"


# ------------------------------------------------------------
# BÚSQUEDA WEB DISCOVERY ENGINE
# ------------------------------------------------------------
def nico_web_search(query):
    PROJECT_ID = "chat-nico"
    DATASTORE_ID = "umich-sitios-oficiales_1763519658833"
    LOCATION = "global"
    COLLECTION = "default_collection"

    token = get_access_token()
    if not token:
        return {"error": "No OAuth token"}

    url = (
        f"https://discoveryengine.googleapis.com/v1alpha/"
        f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/{COLLECTION}/"
        f"dataStores/{DATASTORE_ID}:search"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "query": query,
        "pageSize": 5,
        "queryExpansionSpec": {"condition": "AUTO"},
        "spellCorrectionSpec": {"mode": "AUTO"},
        "languageCode": "es",
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


# ------------------------------------------------------------
# VOZ EN NAVEGADOR (más grave y masculina)
# ------------------------------------------------------------
def speak_browser(text: str):
    text_json = json.dumps(text)
    js = f"""
    <script>
        const s = window.speechSynthesis;
        const utter = new SpeechSynthesisUtterance({text_json});

        function pickVoice() {{
            let voices = s.getVoices();
            let chosen = null;

            // Preferir voces masculinas neutras y graves
            const preferred = ["male", "hombre", "manuel", "miguel", "diego", "jorge"];

            for (let v of voices) {{
                let name = v.name.toLowerCase();
                let lang = v.lang.toLowerCase();
                if (lang.startsWith("es")) {{
                    for (let pref of preferred) {{
                        if (name.includes(pref)) {{
                            chosen = v;
                            break;
                        }}
                    }}
                }}
                if (chosen) break;
            }}

            if (!chosen) {{
                // fallback español
                for (let v of voices) {{
                    if (v.lang.toLowerCase().startsWith("es")) {{
                        chosen = v;
                        break;
                    }}
                }}
            }}

            if (chosen) utter.voice = chosen;
            utter.pitch = 0.7;  // voz más grave
            utter.rate = 0.95;  // más pausada y neutra

            s.speak(utter);
        }}

        if (s.getVoices().length === 0) {{
            s.addEventListener('voiceschanged', pickVoice);
        }} else {{
            pickVoice();
        }}
    </script>
    """
    components.html(js, height=0)


# ============================================================
# INTERFAZ PRINCIPAL
# ============================================================

ensure_session_defaults()
exchange_code_for_token()

if not st.session_state["logged"]:
    login_view()
    st.stop()

st.markdown(header_html(), unsafe_allow_html=True)

conv_col, video_col = st.columns([0.7, 0.3])

with conv_col:

    user_msg = st.text_input("Escribe tu pregunta:")

    if st.button("Enviar") and user_msg.strip():

        # ---------- BÚSQUEDA WEB -----------
        search_results = nico_web_search(user_msg)
        snippets = []

        if "results" in search_results:
            for item in search_results["results"]:
                doc = item.get("document", {})
                text = doc.get("structData", {}).get("text", "")
                if text:
                    snippets.append(text[:400])

        web_context = "\n\n".join(snippets) if snippets else "No hay información oficial encontrada."

        # ---------- PROMPT PARA GEMINI -----------
        prompt = f"""
Eres NICO, asistente institucional de la UMSNH.

Consulta del usuario:
{user_msg}

Contexto oficial obtenido de sitios UMSNH:
{web_context}

Responde de manera clara, útil y verificable.
"""

        reply = gemini_generate(
            prompt,
            st.session_state["temperature"],
            st.session_state["top_p"],
            st.session_state["max_tokens"],
        )

        st.session_state["history"].append({"role": "user", "content": user_msg})
        st.session_state["history"].append({"role": "assistant", "content": reply})

        st.rerun()

    # Mostrar historial
    for msg in st.session_state["history"]:
        if msg["role"] == "user":
            st.chat_message("user").markdown(msg["content"])
        else:
            st.chat_message("assistant").markdown(msg["content"])
            if st.session_state["voice_on"]:
                speak_browser(msg["content"])
