
import asyncio
import edge_tts

VOICE = "es-MX-JorgeNeural"
RATE = "+0%"
VOLUME = "+0%"

def synthesize_edge_tts(text: str) -> bytes:
    async def _run():
        communicate = edge_tts.Communicate(text, VOICE, rate=RATE, volume=VOLUME)
        mp3_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_data += chunk["data"]
        return mp3_data
    try:
        return asyncio.run(_run())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        data = loop.run_until_complete(_run())
        loop.close()
        return data
