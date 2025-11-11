# NICO OAuth Moderno (Streamlit)
Login con Google OAuth, UI moderna, Voz ON/OFF, y sliders de modelo.

## Local
cp .env.example .env
pip install -r requirements.txt
streamlit run app.py

## Cloud
- Sube todo el repo a GitHub.
- En Streamlit Cloud agrega en Secrets:
  GEMINI_API_KEY="..."
- En Google Auth agrega el dominio de tu app a **Orígenes** y usa la URL de la app como **Redirect URI**.
- Ajusta GOOGLE_REDIRECT_URI a la URL pública en Secrets.
