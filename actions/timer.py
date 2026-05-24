import time
import threading

_active_timer_event = threading.Event()
_active_timer_thread = None

def timer_action(parameters: dict, player=None, speak=None) -> str:
    global _active_timer_event, _active_timer_thread
    
    action = parameters.get("action", "start")
    
    if action == "cancel":
        if _active_timer_thread and _active_timer_thread.is_alive():
            _active_timer_event.set()
            if player and hasattr(player, "cancel_timer"):
                player.cancel_timer()
            return "Timer cancelled successfully."
        return "There is no active timer to cancel."

    duration_str = str(parameters.get("duration_seconds", 0))
    try:
        duration_seconds = float(duration_str)
    except ValueError:
        return "Invalid duration provided."
    
    message = parameters.get("message", "Timer is up!")
    
    if duration_seconds <= 0:
        return "Timer duration must be positive."

    # Cancel any existing timer
    if _active_timer_thread and _active_timer_thread.is_alive():
        _active_timer_event.set()
        _active_timer_thread.join(timeout=1.0)
        
    _active_timer_event.clear()

    def _run_timer():
        # wait returns True if the flag was set (cancelled)
        cancelled = _active_timer_event.wait(duration_seconds)
        if not cancelled:
            if player:
                player.write_log(f"[Timer] ⏰ {message}")
                if hasattr(player, "notify"):
                    player.notify("Timer Finished", f"{message}")
            if speak:
                speak(f"[SYSTEM INSTRUCTION: The timer just finished! Tell the user: 'Sir, your timer is up. {message}']")

    _active_timer_thread = threading.Thread(target=_run_timer, daemon=True, name=f"JarvisTimer_{int(time.time())}")
    _active_timer_thread.start()
    
    if player and hasattr(player, "start_timer_countdown"):
        player.start_timer_countdown(duration_seconds, message)
    elif player and hasattr(player, "notify"):
        player.notify("Timer Started", f"Timer set for {duration_seconds} seconds")
    
    return f"Timer started for {duration_seconds} seconds."
