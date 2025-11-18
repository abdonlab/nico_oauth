# ============================================================
# Google Cloud Text-to-Speech para NICO (voz masculina)
# Compatible con Streamlit Cloud
# ============================================================

from google.cloud import texttospeech

# Voz masculina profesional de México
VOICE_NAME = "es-MX-Standard-B"
AUDIO_ENCODING = texttospeech.AudioEncoding.MP3

def synthesize_edge_tts(text: str) -> bytes:
    """
    Genera voz masculina con Google Cloud TTS y devuelve bytes MP3.
    """
    try:
        # Cliente de Google TTS
        client = texttospeech.TextToSpeechClient()

        # Texto a sintetizar
        synthesis_input = texttospeech.SynthesisInput(text=text)

        # Selección de voz masculina
        voice = texttospeech.VoiceSelectionParams(
            language_code="es-MX",
            name=VOICE_NAME,
            ssml_gender=texttospeech.SsmlVoiceGender.MALE,
        )

        # Configuración del audio
        audio_config = texttospeech.AudioConfig(
            audio_encoding=AUDIO_ENCODING,
            speaking_rate=1.05,   # velocidad natural
            pitch=-2.0,           # tono masculino profundo
        )

        # Generar voz
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )

        return response.audio_content

    except Exception as e:
        print("Error en TTS:", e)
        return None
