import asyncio
import os
import tempfile
import pygame
import edge_tts
from memory.memory_manager import load_memory

class ReadingEngine:
    """Dedicated offline TTS engine for reading extremely long texts."""
    
    def __init__(self, voice="en-US-ChristopherNeural"):
        self.voice = voice
        self.is_playing = False
        self._current_task = None
        # Initialize pygame mixer only when needed to avoid locking audio devices
    
    async def read_aloud(self, text: str, voice_override: str = None):
        """Generates TTS audio and plays it in chunks."""
        
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
            
            # 1. Clean Markdown
            # Remove link syntax: [text](url) -> text
            clean_text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
            # Remove common formatting symbols
            clean_text = re.sub(r'[*_#>`~-]', '', clean_text)
            
            # 2. Chunk the text into smaller pieces to avoid edge-tts API limits and long delays
            sentences = re.split(r'(?<=[.!?\n])\s+', clean_text)
            chunks = []
            current_chunk = ""
            for sentence in sentences:
                if len(current_chunk) + len(sentence) < 2000:
                    current_chunk += sentence + " "
                else:
                    if current_chunk: chunks.append(current_chunk.strip())
                    current_chunk = sentence + " "
            if current_chunk:
                chunks.append(current_chunk.strip())

            if not pygame.mixer.get_init():
                pygame.mixer.init()

            audio_queue = asyncio.Queue()

            async def generate_chunks():
                for i, chunk in enumerate(chunks):
                    if self._stop_requested:
                        break
                    
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                    temp_filename = temp_file.name
                    temp_file.close()
                    
                    # Retry logic for network/API limits
                    success = False
                    for attempt in range(3):
                        try:
                            communicate = edge_tts.Communicate(chunk, self.voice, rate='+10%')
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
