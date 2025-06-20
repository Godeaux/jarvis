"""
Main Jarvis voice assistant orchestrator.

This module coordinates the voice assistant's core functionality, including:
- Wake word detection
- Speech-to-text transcription
- Command interpretation
- Text-to-speech response
- Music control via REST API integration

The assistant maintains a single shared microphone stream for efficiency
and provides voice control over a remote music bot service.
"""

from wake_word import wait_for_wake_word
from transcribe import record_and_transcribe
from pynput.keyboard import Controller
from dotenv import load_dotenv
import pyttsx3
import requests
import pyaudio
import os
import time
import threading
import queue

# ─── console formatting helpers ──────────────────────────────────────────
GREEN = "\033[92m"
BOLD = "\033[1m"
RESET = "\033[0m"


def log_packet(command: str, payload: dict) -> None:
    """Print a single-line confirmation that a packet was sent."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {GREEN}sent:{RESET} {command} {payload}")

# Initialize environment variables and global service objects
load_dotenv()                                 # Load configuration from .env file
keyboard = Controller()                       # For potential keyboard control

# ─── async, interruptible text-to-speech ────────────────────────────────
class AsyncTTS:
    """Threaded pyttsx3 wrapper with .speak_async() and .stop()."""
    def __init__(self):
        self._q = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _worker(self):
        self.engine = pyttsx3.init()
        for text in iter(self._q.get, None):   # sentinel None shuts down
            self.engine.say(text)
            self.engine.runAndWait()

    # enqueue text, return immediately
    def speak_async(self, text: str):
        self._q.put(text)

    # interrupt current speech instantly
    def stop(self):
        if hasattr(self, "engine"):
            self.engine.stop()

    # clean shutdown (call in main finally:)
    def shutdown(self):
        self._q.put(None)

tts = AsyncTTS()                              # Async text-to-speech engine

# Music bot configuration from environment
guild_id = os.getenv("GUILD_ID")             # Discord server ID
user_id = os.getenv("USER_ID")               # User's Discord ID
voice_channel_id = os.getenv("VOICE_CHANNEL_ID")  # Target voice channel

# Configure and initialize shared audio input stream
RATE = 16_000                                # Sample rate in Hz
CHUNK = 512                                  # Buffer size (matches Porcupine)
_pa = pyaudio.PyAudio()
shared_stream = _pa.open(format=pyaudio.paInt16,
                        channels=1,
                        rate=RATE,
                        input=True,
                        frames_per_buffer=CHUNK)

def send_play_command(song_name: str):
    """
    Send request to music bot to play a specific song.

    Args:
        song_name: Name/query of the song to play

    Returns:
        dict: Response from the music bot API, or None on failure
    """
    url = "https://vibesbot.no-vibes.com/command/play"
    payload = {
        "guildId": guild_id,
        "userId": user_id,
        "voiceChannelId": voice_channel_id,
        "options": {"query": song_name}
    }
    try:
        response = requests.post(url, json=payload).json()
        log_packet("/play", payload)
        return response
    except Exception as e:
        print("Play request failed:", e)

def send_command(command: str):
    """
    Send a control command to the music bot.

    Args:
        command: Command name (e.g., 'pause', 'resume', 'stop')

    Returns:
        dict: Response from the music bot API, or None on failure
    """
    url = f"https://vibesbot.no-vibes.com/command/{command}"
    payload = {
        "guildId": guild_id,
        "userId": user_id,
        "voiceChannelId": voice_channel_id,
        "options": {}
    }
    try:
        response = requests.post(url, json=payload).json()
        log_packet(command, payload)
        return response
    except Exception as e:
        print("Command request failed:", e)

def listen_for_voice_commands():
    """
    Main voice command loop.
    
    Continuously listens for wake word, transcribes subsequent speech,
    interprets commands, and executes appropriate actions. Supports
    music playback control and self-termination commands.
    """
    while True:
        print(f"{BOLD}Say 'Jarvis' to wake...{RESET}")
        wait_for_wake_word(shared_stream)           # Wait for activation
        tts.stop()   # interrupt any ongoing speech
        print(f"{GREEN}Wake word detected.{RESET}")
        tts.speak_async("Yes???")  # Acknowledge wake word
        transcript = ""
        for partial in record_and_transcribe(shared_stream):
            # overwrite the current line with the growing sentence
            print('\r' + partial + ' ' * 20, end='', flush=True)
            transcript = partial          # will end up holding the final yield
        print()                           # newline after the overwrite loop
        print(f"{BOLD}You said:{RESET} {transcript}")


        # Command interpretation and execution
        if ("now" in transcript and "playing" in transcript):
            tts.speak_async("Now playing.")
            send_command("now-playing")
        elif "played" in transcript:
            # Handle alternative phrasing for play command
            song = transcript.replace("played", "", 1).strip()
            if song:
                tts.speak_async(f"Playing {song}")
                send_play_command(song)
        elif "play" in transcript:
            song = transcript.replace("play", "", 1).strip()
            if song:
                tts.speak_async(f"Playing {song}")
                send_play_command(song)
        # Basic playback controls
        elif "stop"   in transcript: tts.speak_async("Stopping.");  send_command("stop")
        elif "pause"  in transcript: tts.speak_async("Pausing.");   send_command("pause")
        elif "resume" in transcript: tts.speak_async("Resuming.");  send_command("resume")
        elif "next"   in transcript: tts.speak_async("Skipping.");  send_command("next")
        elif "clear"  in transcript: tts.speak_async("Clearing.");  send_command("clear")
        # Exit commands
        elif ("kill" in transcript and "self" in transcript) or \
             ("self" in transcript and "destruct" in transcript):
            tts.speak_async("Goodbye.")
            break
        else:
            tts.speak_async("Sorry, I didn't understand that command.")

def main():
    """
    Entry point: Initialize and run the voice assistant.
    
    Ensures proper cleanup of audio resources on exit.
    """
    try:
        print("=" * 40)
        print(f"{BOLD}      JARVIS VOICE ASSISTANT      {RESET}")
        print("=" * 40)
        print()
        listen_for_voice_commands()
    finally:
        # Clean up audio resources
        shared_stream.close()
        _pa.terminate()
        tts.shutdown()

if __name__ == "__main__":
    main()
