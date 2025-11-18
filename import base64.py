import base64
import google.generativeai as genai

# ------------------------------------------------------------
# CONFIGURACIÓN DEL MODELO DE VOZ
# ------------------------------------------------------------
VOICE_NAME = "Aoede"  
# Voces disponibles: 
#   * Aoede (neutral/masculina)
#   * Kore (femenina)
#   * Charis (neutral)
#   * Cyril (masculina)
#   * Dana (femenina)

MODEL_TTS = "gemini-2.0-flash"   # Modelo compatible con audio TTS


# ------------------------------------------------------------
# FUNCIONES PARA GENERAR VOZ
# ------------------------------------------------------------
def synthesize_tts(texto: str) -> bytes:
    """
    Genera audio MP3 usando Google Gemini TTS.
    Retorna un audio en formato bytes.
    """

    if not texto or texto.strip() == "":
        texto = "No se recibió ningún texto para convertir a voz."

    try:
        model = genai.GenerativeModel(MODEL_TTS)
        audio_response = model.generate_content(
            [
                texto,
                {
                    "mime_type": "audio/mp3",
                    "voice": VOICE_NAME,
                    "speed": 1.0
                }
            ]
        )

        # Gemini devuelve el audio en base64
        audio_bytes = audio_response._result.audio.data
        return audio_bytes

    except Exception as e:
        print("❌ Error generando voz TTS:", e)
        return None


def save_audio_file(audio_bytes: bytes, filename: str) -> str:
    """
    Guarda un audio en disco y regresa la ruta.
    """
    if audio_bytes is None:
        return None

    try:
        with open(filename, "wb") as f:
            f.write(audio_bytes)
        return filename
    except Exception as e:
        print("❌ Error guardando audio:", e)
        return None