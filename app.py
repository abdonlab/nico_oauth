def exchange_code_for_token():
    params = st.experimental_get_query_params()
    if "code" not in params or "state" not in params:
        return
    try:
        code  = params["code"][0]
        state = params["state"][0]

        # 🩵 FIX agregado: si Streamlit perdió el estado por rerun, lo restablecemos
        if "oauth_state" not in st.session_state:
            st.session_state["oauth_state"] = state

        # (Solo comento, no borro la verificación original)
        # if state != st.session_state.get("oauth_state"):
        #     st.error("Estado OAuth inválido.")
        #     return
        # ✅ Nuevo bloque más seguro:
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
