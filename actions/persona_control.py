import os
from memory.memory_manager import update_memory

def persona_control(parameters: dict, player=None) -> str:
    """
    Changes JARVIS's voice persona.
    Voices available: Charon, Aoede, Puck, Kore.
    """
    params = parameters or {}
    action = params.get("action", "change_voice")
    voice  = params.get("voice_name", "").capitalize().strip()
    
    valid_voices = ["Charon", "Aoede", "Puck", "Kore"]
    
    if voice not in valid_voices:
        return f"Voice '{voice}' is not recognized. Available voices: {', '.join(valid_voices)}."
    
    # Save to memory
    update_memory({"settings": {"active_voice": {"value": voice}}})
    
    if player and hasattr(player, "request_reconnect"):
        player.request_reconnect()
        return f"Switching to the {voice} persona now, sir. One moment."

    return f"Voice persona switched to {voice}, sir. This will take effect on our next connection."
