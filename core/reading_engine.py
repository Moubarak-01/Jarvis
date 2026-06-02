import asyncio
import os
import tempfile
import pygame
import edge_tts
import json
from google import genai
from google.genai import types
from memory.memory_manager import load_memory

class ReadingEngine:
    """Dedicated offline TTS engine for reading extremely long texts and dialogues."""
    
    def __init__(self, voice="en-US-ChristopherNeural"):
        self.voice = voice
        self.is_playing = False
        self._current_task = None
        # Extended voice pool for dialogues
        self.voice_pool = [
            "en-US-SteffanNeural", "en-US-JennyNeural", "en-GB-RyanNeural", 
            "en-AU-NatashaNeural", "en-CA-LiamNeural", "en-IE-ConnorNeural",
            "en-NZ-MitchellNeural", "en-ZA-LukeNeural", "en-US-AriaNeural",
            "en-GB-SoniaNeural", "en-US-GuyNeural"
        ]
        
    async def _analyze_text(self, text: str) -> dict:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return {"is_dialogue": False}
        try:
            client = genai.Client(api_key=api_key)
            prompt = (
                "Analyze the following text to determine if it is a dialogue/script with multiple speakers, "
                "or just a normal article/text block. If it is a dialogue, extract the segments in order. "
                "If it's an article but has quotes, treat it as normal (is_dialogue: false) unless it is distinctly formatted as a script.\n\n"
                f"TEXT:\n{text[:5000]}"
            )
            
            response = await client.aio.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema={
                        "type": "OBJECT",
                        "properties": {
                            "is_dialogue": {"type": "BOOLEAN"},
                            "segments": {
                                "type": "ARRAY",
                                "items": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "speaker": {"type": "STRING"},
                                        "text": {"type": "STRING"}
                                    },
                                    "required": ["speaker", "text"]
                                }
                            }
                        },
                        "required": ["is_dialogue"]
                    }
                )
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"[ReadingEngine] AI Analysis failed: {e}")
            return {"is_dialogue": False}
            
    async def read_aloud(self, text: str, voice_override: str = None):
        """Generates TTS audio and plays it in chunks, supporting dialogues."""
        
        # Dynamically fetch the current persona voice from memory
        memory = load_memory()
        active_persona = voice_override if voice_override else memory.get("settings", {}).get("active_voice", {}).get("value", "Charon")
        
        # Map Gemini Personas to Edge-TTS Voices
        voice_map = {
            "Charon": "en-US-ChristopherNeural",  # Deep, authoritative male
            "Puck": "en-US-GuyNeural",            # Bright, younger male
            "Aoede": "en-US-AriaNeural",          # Smooth, professional female
            "Kore": "en-GB-SoniaNeural"           # British, articulate female
        }
        self.voice = voice_map.get(active_persona, "en-US-ChristopherNeural")
        
        self.is_playing = True
        self._stop_requested = False
        self._pause_requested = False
        self.is_paused = False
        try:
            import re
            
            # Analyze text to see if it's a dialogue
            analysis = await self._analyze_text(text)
            is_dialogue = analysis.get("is_dialogue", False)
            
            chunks = []
            
            if is_dialogue and "segments" in analysis and analysis["segments"]:
                print("[ReadingEngine] Dialogue detected! Assigning voices...")
                speaker_voices = {}
                available_voices = self.voice_pool.copy()
                
                for seg in analysis["segments"]:
                    spk = seg["speaker"]
                    txt = seg["text"]
                    spk_lower = spk.lower().strip()
                    
                    # Assign narrator/user to default voice
                    if spk_lower in ["me", "self", "narrator", "author"]:
                        v = self.voice
                    else:
                        if spk not in speaker_voices:
                            v = available_voices.pop(0) if available_voices else "en-US-AriaNeural"
                            speaker_voices[spk] = v
                        else:
                            v = speaker_voices[spk]
                            
                    # Chunk the segment text
                    clean_txt = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', txt)
                    clean_txt = re.sub(r'[*_#>`~-]', '', clean_txt)
                    sentences = re.split(r'(?<=[.!?\n])\s+', clean_txt)
                    current_chunk = ""
                    for sentence in sentences:
                        if len(current_chunk) + len(sentence) < 2000:
                            current_chunk += sentence + " "
                        else:
                            if current_chunk: chunks.append({"voice": v, "text": current_chunk.strip()})
                            current_chunk = sentence + " "
                    if current_chunk:
                        chunks.append({"voice": v, "text": current_chunk.strip()})
            else:
                # Normal reading
                clean_text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
                clean_text = re.sub(r'[*_#>`~-]', '', clean_text)
                sentences = re.split(r'(?<=[.!?\n])\s+', clean_text)
                current_chunk = ""
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) < 2000:
                        current_chunk += sentence + " "
                    else:
                        if current_chunk: chunks.append({"voice": self.voice, "text": current_chunk.strip()})
                        current_chunk = sentence + " "
                if current_chunk:
                    chunks.append({"voice": self.voice, "text": current_chunk.strip()})

            if not pygame.mixer.get_init():
                pygame.mixer.init()

            audio_queue = asyncio.Queue()

            async def generate_chunks():
                for i, chunk_data in enumerate(chunks):
                    if self._stop_requested:
                        break
                    
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                    temp_filename = temp_file.name
                    temp_file.close()
                    
                    chunk_text = chunk_data["text"]
                    chunk_voice = chunk_data["voice"]
                    
                    # Retry logic for network/API limits
                    success = False
                    for attempt in range(3):
                        try:
                            communicate = edge_tts.Communicate(chunk_text, chunk_voice, rate='+10%')
                            await communicate.save(temp_filename)
                            success = True
                            break
                        except Exception as e:
                            print(f"[ReadingEngine] Chunk {i} attempt {attempt+1} failed: {e}")
                            await asyncio.sleep(1.5)
                            
                    if success and not self._stop_requested:
                        await audio_queue.put(temp_filename)
                    else:
                        if not success:
                            print(f"[ReadingEngine] Skipping chunk {i} after 3 failed attempts.")
                        try:
                            os.remove(temp_filename)
                        except Exception:
                            pass
                            
                await audio_queue.put(None)  # EOF marker

            # Start downloading chunks in the background
            asyncio.create_task(generate_chunks())
            
            # Play them back as soon as they are ready
            while not self._stop_requested:
                temp_filename = await audio_queue.get()
                if temp_filename is None:
                    break
                    
                if self._stop_requested:
                    try:
                        os.remove(temp_filename)
                    except Exception:
                        pass
                    break
                    
                try:
                    pygame.mixer.music.load(temp_filename)
                    pygame.mixer.music.play()
                    
                    while (pygame.mixer.music.get_busy() or self.is_paused) and not self._stop_requested:
                        if self._pause_requested and not self.is_paused:
                            pygame.mixer.music.pause()
                            self.is_paused = True
                        elif not self._pause_requested and self.is_paused:
                            pygame.mixer.music.unpause()
                            self.is_paused = False
                            
                        await asyncio.sleep(0.05)
                        
                finally:
                    try:
                        pygame.mixer.music.unload() # Free the file so it can be deleted
                        os.remove(temp_filename)
                    except Exception as e:
                        pass
                        
        except Exception as e:
            print(f"[ReadingEngine] Error during reading: {e}")
            raise
        finally:
            self.is_playing = False
            self.is_paused = False
            self._stop_requested = False
            self._pause_requested = False

    def stop(self):
        """Stops the current playback."""
        self._stop_requested = True
        self._pause_requested = False
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
        self.is_playing = False
        self.is_paused = False

    def pause(self):
        """Pauses the reading engine."""
        self._pause_requested = True

    def resume(self):
        """Resumes the reading engine."""
        self._pause_requested = False

# Global singleton
reading_engine = ReadingEngine()
