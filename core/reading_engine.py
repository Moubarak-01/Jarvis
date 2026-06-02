import asyncio
import os
import tempfile
import pygame
import edge_tts
import json
import re
from memory.memory_manager import load_memory
from core.llm_helper import generate_content_with_waterfall

class ReadingEngine:
    """Dedicated offline TTS engine for reading extremely long texts and mixed-dialogues."""
    
    def __init__(self, voice="en-US-ChristopherNeural"):
        self.voice = voice
        self.is_playing = False
        self._current_task = None
        self._stop_requested = False
        self._pause_requested = False
        self.is_paused = False
        # Extended voice pool for dialogues
        self.voice_pool = [
            "en-US-SteffanNeural", "en-US-JennyNeural", "en-GB-RyanNeural", 
            "en-AU-NatashaNeural", "en-CA-LiamNeural", "en-IE-ConnorNeural",
            "en-NZ-MitchellNeural", "en-ZA-LukeNeural", "en-US-AriaNeural",
            "en-GB-SoniaNeural", "en-US-GuyNeural"
        ]

    def _regex_parse_dialogue(self, text):
        """Attempts to parse dialogue locally. Returns None if ambiguous or not a dialogue."""
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
        segments = []
        dialogue_count = 0
        
        # Match Speaker Name (Action): Text
        pattern = re.compile(r'^(?:\*\*|\*|_)?([A-Za-z0-9\s-]{2,15}?)(?:\*\*|\*|_)?\s*(?:\((.*?)\))?\s*(?:\*\*|\*|_)?:\s*(?:\*\*|\*|_)?(.*)', re.DOTALL)
        
        for p in paragraphs:
            match = pattern.match(p)
            if match:
                speaker = match.group(1).strip()
                action = match.group(2)
                spoken = match.group(3).strip()
                
                # Check for suspicious markdown headers being matched as speakers
                if speaker.lower().startswith("the ") or len(speaker) > 15:
                    return None # Ambiguous, fallback to API
                    
                text_out = f"({action}) {spoken}" if action else spoken
                segments.append({"type": "dialogue", "speaker": speaker, "text": text_out})
                dialogue_count += 1
            else:
                segments.append({"type": "normal", "text": p})
                
        # Only use regex if we confidently found a multi-line dialogue
        if dialogue_count < 2:
            return None 
            
        return segments
            
    async def read_aloud(self, text: str, voice_override: str = None):
        """Generates TTS audio and plays it in chunks, dynamically handling mixed articles and dialogues."""
        
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
            # 1. Try Fast Local Regex Parsing
            segments = self._regex_parse_dialogue(text)
            
            # 2. API Fallback if Regex fails or is ambiguous
            if segments is None:
                print("[ReadingEngine] Regex parsing ambiguous, falling back to API parser...")
                prompt = (
                    "You are an advanced text parser. Analyze the following text and segment it into sequential reading chunks. "
                    "The text may contain standard article paragraphs, section headers, AND multi-speaker dialogue scripts.\n\n"
                    "RULES:\n"
                    "1. If a section is a normal article, header, or paragraph, classify it as type='normal' and put the text in the 'text' field. Do not extract speaker for normal sections.\n"
                    "2. If a section is a scripted dialogue, extract ONLY the character's base name (e.g., 'Elena', 'Me') for the 'speaker' field. Do NOT put actions or parentheses in the speaker field.\n"
                    "3. CRITICAL: For dialogue segments, you MUST extract any parenthetical thoughts, actions, or stage directions (e.g., '(Kinetic Mask \u2014 ...)') and prepend them inside the 'text' field so they are spoken out loud. Example: If the raw text is 'Elena (Angry): Stop!', the output text MUST be '(Angry) Stop!'. Do NOT discard them!\n"
                    "4. Output a JSON array of these segment objects in the exact order they appear.\n\n"
                    f"TEXT:\n{text[:8000]}"
                )
    
                config_dict = {
                    "response_mime_type": "application/json",
                    "response_schema": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "type": {"type": "STRING"},
                                "speaker": {"type": "STRING"},
                                "text": {"type": "STRING"}
                            },
                            "required": ["type", "text"]
                        }
                    }
                }
    
                try:
                    response = await asyncio.to_thread(
                        generate_content_with_waterfall,
                        prompt,
                        None,  # system_instruction
                        False, # is_vision
                        config_dict,
                        True   # prefer_fast
                    )
                    segments = json.loads(response.text)
                except Exception as e:
                    print(f"[ReadingEngine] API Analysis failed, defaulting to normal reading: {e}")
                    segments = [{"type": "normal", "text": text}]
            
            chunks = []
            speaker_voices = {}
            available_voices = self.voice_pool.copy()
            
            for seg in segments:
                seg_type = seg.get("type", "normal")
                txt = seg.get("text", "")
                
                if seg_type == "dialogue":
                    spk = seg.get("speaker", "Unknown")
                    spk_lower = spk.lower().strip()
                    
                    if spk_lower in ["me", "self", "narrator", "author"]:
                        v = self.voice
                    else:
                        if spk_lower not in speaker_voices:
                            v = available_voices.pop(0) if available_voices else "en-US-AriaNeural"
                            speaker_voices[spk_lower] = v
                        else:
                            v = speaker_voices[spk_lower]
                else:
                    v = self.voice
                        
                # Chunk the segment text to avoid Edge-TTS limits
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
