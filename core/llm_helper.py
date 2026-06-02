# core/llm_helper.py
import time
from google import genai
from google.genai import types as gtypes
from typing import List, Optional, Any, Dict
from memory.config_manager import get_gemini_key

# --- THE UNIFIED WATERFALL ---
# Any model in this list must support Multimodal (Vision) input.
WATERFALL_MODELS = [
    { "type": "gemini", "model": "gemini-3.1-flash-lite-preview", "name": "Gemini 3.1 Flash Lite" },
    { "type": "gemini", "model": "gemini-3.5-flash", "name": "Gemini 3.5 Flash" },
    { "type": "gemini", "model": "gemini-2.5-flash", "name": "Gemini 2.5 Flash" },
    { "type": "gemini", "model": "gemini-2.0-flash-lite-preview-02-05", "name": "Gemini 2.0 Flash Lite" },
    { "type": "gemini", "model": "gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash Lite" },
    { "type": "gemini", "model": "gemini-3-flash-preview", "name": "Gemini 3 Flash" },
    { "type": "gemini", "model": "gemini-2.5-pro", "name": "Gemini 2.5 Pro" },
    { "type": "gemini", "model": "gemma-4-26b-a4b-it", "name": "Gemma 4 26B" },
    { "type": "gemini", "model": "gemma-4-31b-it", "name": "Gemma 4 31B" },
    { "type": "gemini", "model": "gemini-2.5-flash-native-audio-preview-12-2025", "name": "Gemini 2.5 Audio (Unlimited)" }
]

def generate_content_with_waterfall(
    prompt: Any, 
    system_instruction: Optional[str] = None,
    is_vision: bool = False, # Parameter kept for compatibility, but ignored
    config: Optional[Dict] = None,
    prefer_fast: bool = False
) -> Any:
    """
    Tries to generate content using the unified model waterfall.
    """
    api_key = get_gemini_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not found.")
    
    client = genai.Client(api_key=api_key)
    
    last_error = None
    
    models_to_try = WATERFALL_MODELS.copy()
    if prefer_fast:
        for i, m in enumerate(models_to_try):
            if m["model"] == "gemini-3.1-flash-lite-preview":
                fast_model = models_to_try.pop(i)
                models_to_try.insert(0, fast_model)
                break

    for model_info in models_to_try:
        model_name = model_info["model"]
        try:
            print(f"[LLM] Trying model: {model_info['name']} ({model_name})...")
            
            # Merge system instruction into config if provided
            final_config = config.copy() if config else {}
            if system_instruction:
                final_config["system_instruction"] = system_instruction

            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=final_config if final_config else None
            )
            
            # Extract text and handle non-data parts warning
            text_parts = []
            try:
                for candidate in response.candidates:
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, "text") and part.text:
                                text_parts.append(part.text)
                
                class CleanResponse:
                    def __init__(self, text, original):
                        self.text = text
                        self.original = original
                    def __getattr__(self, name):
                        return getattr(self.original, name)

                print(f"[LLM] \u2705 Successfully used model: {model_name}")
                return CleanResponse("".join(text_parts), response)
            except Exception:
                print(f"[LLM] \u2705 Successfully used model: {model_name} (Raw format)")
                return response

        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            if "not found" in error_str or "404" in error_str or "429" in error_str or "limit" in error_str or "permission" in error_str:
                print(f"[LLM] ⚠️ Model {model_name} failed/unavailable: {e}")
                continue
            else:
                print(f"[LLM] ⚠️ Model {model_name} error: {e}")
                continue

    raise RuntimeError(f"All models in waterfall failed. Last error: {last_error}")
