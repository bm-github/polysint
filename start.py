import subprocess
import sys
import time
from datetime import datetime
from logger import get_logger
from notifier import Notifier

log = get_logger("System")

# Set how often you want the Heartbeat check-in (in seconds)
# 21600 = 6 hours. (Change to 3600 for 1 hour, or 60 for testing)
HEARTBEAT_INTERVAL = 21600 

def start_engine():
    print("🚀 Starting PolySINT Engine...")
    processes =[]
    notifier = Notifier()

    try:
        # 1. Start the FastAPI Server
        print(" -> Launching API Server (Port 9000)...")
        api_proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "api:app", "--port", "9000"])
        processes.append(("API Server", api_proc))
        time.sleep(2)

        # 2. Start the Harvester
        print(" -> Launching Data Harvester...")
        harvest_proc = subprocess.Popen([sys.executable, "harvest.py"])
        processes.append(("Harvester Worker", harvest_proc))

        # 3. Start the Alerts
        print(" -> Launching Anomaly Detector...")
        alerts_proc = subprocess.Popen([sys.executable, "alerts.py"])
        processes.append(("Alerts Worker", alerts_proc))

        # 4. Start the Watcher
        print(" -> Launching Whale Watcher...")
        watcher_proc = subprocess.Popen([sys.executable, "watcher.py"])
        processes.append(("Watcher Worker", watcher_proc))

        print("\n✅ All systems nominal! PolySINT is fully operational.")
        print("🛑 Press[Ctrl + C] to safely shut down all systems.\n")

        # Send Boot Alert
        notifier.broadcast(
            message="**All PolySINT daemon workers have been successfully launched.**\nAwaiting anomalies and entity movements...",
            title="🚀 System Boot: Online"
        )

        last_heartbeat = time.time()

        # The Heartbeat Loop
        while True:
            time.sleep(10) # Quick loop so Ctrl+C stays responsive
            current_time = time.time()
            
            # If the interval has passed, run the health check
            if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                status_msg = "**Periodic Health Check:**\n"
                all_healthy = True
                
                for name, p in processes:
                    # p.poll() is None means the process is still running perfectly
                    if p.poll() is None:
                        status_msg += f"🟢 **{name}**: Online\n"
                    else:
                        status_msg += f"🔴 **{name}**: Offline (Crashed)\n"
                        all_healthy = False
                
                # Change title/color based on health
                title = "💚 System Heartbeat" if all_healthy else "⚠️ System Degraded"
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Sending Heartbeat to Discord...")
                notifier.broadcast(message=status_msg, title=title)
                
                last_heartbeat = current_time

    except KeyboardInterrupt:
        print("\n\n⚠️ Shutting down PolySINT Engine...")
        
        # Send Shutdown Alert
        notifier.broadcast(message="System was manually shut down by the administrator.", title="🛑 System Offline")
        
        for name, p in processes:
            print(f" -> Stopping {name}...")
            p.terminate() 
            p.wait()      
        print("🛑 Shutdown complete. Goodbye!")
        sys.exit(0)

if __name__ == "__main__":
    start_engine()