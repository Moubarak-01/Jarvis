# actions/system_status.py

def system_status(parameters: dict = None, response=None, player=None, session_memory=None) -> str:
    if not player:
        return "No player (UI) available to read system status."
    
    try:
        action = parameters.get("action", "stats") if parameters else "stats"
        
        if action == "logs":
            # Retrieve the activity log from the UI's LogWidget
            logs = player._win._log.toPlainText()
            return f"Activity Logs:\n{logs}"
            
        elif action == "show_gpu":
            player._win._bar_gpu.show()
            player._win._bar_tmp.show()
            return "GPU and Temperature are now visible on the UI."
            
        elif action == "hide_gpu":
            player._win._bar_gpu.hide()
            player._win._bar_tmp.hide()
            return "GPU and Temperature are now hidden from the UI."
            
        elif action == "stats":
            # Retrieve metrics from the globally available _metrics in ui module
            from ui import _metrics
            snapshot = _metrics.snapshot()
            cpu = snapshot.get("cpu", 0)
            mem = snapshot.get("mem", 0)
            net = snapshot.get("net", 0)
            gpu = snapshot.get("gpu", -1)
            tmp = snapshot.get("tmp", -1)
            
            gpu_str = f"{gpu}%" if gpu >= 0 else "N/A"
            tmp_str = f"{tmp}°C" if tmp >= 0 else "N/A"
            
            stats = (
                f"CPU: {cpu}%\n"
                f"Memory: {mem}%\n"
                f"Network: {net:.2f} MB/s\n"
                f"GPU: {gpu_str}\n"
                f"Temperature: {tmp_str}"
            )
            return f"System Stats:\n{stats}"
            
        else:
            return f"Unknown action: {action}"
            
    except Exception as e:
        return f"Failed to retrieve system status: {e}"
