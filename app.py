# ...
# Selector de vídeo
def pick_video():
    if not videos:
        return None, None
    p = random.choice(videos)
    mime = "video/mp4" if p.suffix.lower() == ".mp4" else "video/webm"
    b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}", mime

# En la columna izquierda, al procesar la pregunta:
if st.button("Enviar") and user_input.strip():
    # 1. Guarda la pregunta
    st.session_state["history"].append({"role": "user", "content": user_input})
    # 2. Elige un nuevo vídeo aleatorio
    data_uri, mime = pick_video()
    st.session_state["current_video"] = (data_uri, mime)
    # 3. Contenedor para reproducir vídeo sólo durante la respuesta
    video_container = st.empty()

    # 4. Prepara y muestra la respuesta
    sys_prompt = "Eres NICO, asistente institucional de la UMSNH. Responde en español."
    prompt = f"{sys_prompt}\n\nUsuario: {user_input}"
    reply = gemini_generate(prompt, st.session_state["temperature"], st.session_state["top_p"], st.session_state["max_tokens"])

    # 5. Inserta el vídeo más pequeño justo antes de mostrar la respuesta
    if data_uri:
        video_container.markdown(
            f"<video width='200' autoplay muted loop playsinline>"
            f"<source src='{data_uri}' type='{mime}' /></video>",
            unsafe_allow_html=True,
        )

    # 6. Añade la respuesta al historial
    st.session_state["history"].append({"role": "assistant", "content": reply})

    # 7. Vacía el contenedor para detener el vídeo al terminar
    video_container.empty()

    # Limpia la entrada y recarga
    st.session_state["user_input"] = ""
    st.experimental_rerun()
