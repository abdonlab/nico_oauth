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
    # Nuevos para el control de input
    st.session_state.setdefault("input_val", "")
    st.session_state.setdefault("trigger_run", False)


def header_html(): # <--- Función movida a este nivel
    """Cabecera visual con icono del zorro 🦊."""
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
    """Pantalla de login con botón de Google."""
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

    # st.query_params para versiones nuevas
    st.query_params["oauth_state"] = state_key
    
    # Botón de Login estilizado (manteniendo el relleno)
    st.markdown(f"""
    <a href="{auth_url}" target="_self" style="
        display: inline-block;
        background-color: #4285F4; /* Azul Google */
        color: white;
        padding: 12px 24px;
        text-decoration: none;
        border-radius: 6px;
        font-family: sans-serif;
        font-weight: bold;
        font-size: 16px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        margin-top: 10px;
    ">
        🔐 Iniciar sesión con Google
    </a>
    """, unsafe_allow_html=True)


def exchange_code_for_token():
    """Intercambiar el código OAuth por tokens y obtener perfil."""
    # CAMBIO IMPORTANTE: Usar st.query_params en lugar de experimental
    try:
        # En nuevas versiones es un objeto tipo dict, no devuelve listas por defecto
        params = st.query_params
        code = params.get("code")
        state = params.get("state")
    except:
        return

    if not code or not state:
        return

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

        st.query_params.clear() # Limpiar URL
        st.rerun() # <--- CORREGIDO

    except Exception as e:
        st.error(f"Error al autenticar: {e}")
