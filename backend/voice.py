from dotenv import load_dotenv
from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs
from elevenlabs.play import play
import os

load_dotenv()

_VOICE_ID = "Nggzl2QAXh3OijoXD116"
_MODEL_ID = "eleven_monolingual_v1"
_OUTPUT_FORMAT = "mp3_44100_128"

_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))


def speak(text: str) -> None:
    audio = _client.text_to_speech.convert(
        text=text,
        voice_id=_VOICE_ID,
        model_id=_MODEL_ID,
        output_format=_OUTPUT_FORMAT,
        voice_settings=VoiceSettings(
            stability=0.5,
            similarity_boost=0.75,
            style=0.0,
            speed=0.7,
        ),
    )
    play(audio)


def play_home_welcome() -> None:
    speak("Hey there. Welcome to BlockedIn.")
