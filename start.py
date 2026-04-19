import subprocess
import sys
import time
import threading
from datetime import datetime
from logger import get_logger
from notifier import Notifier

log = get_logger("System")

HEARTBEAT_INTERVAL = 21600
WORKER_RESTART_DELAY = 10

DAEMON_COMMANDS = {
    "API Server": [sys.executable, "-m", "uvicorn", "api:app", "--port", "9000"],
    "Harvester Worker": [sys.executable, "harvest.py"],
    "Alerts Worker": [sys.executable, "alerts.py"],
    "Watcher Worker": [sys.executable, "watcher.py"],
}

STARTUP_ORDER = ["API Server", "Harvester Worker", "Alerts Worker", "Watcher Worker"]
STARTUP_DELAY = {
    "API Server": 2,
    "Harvester Worker": 2,
    "Alerts Worker": 1,
    "Watcher Worker": 1,
}


def _launch_process(name):
    cmd = DAEMON_COMMANDS[name]
    try:
        proc = subprocess.Popen(cmd)
        log.warning(f"Started {name} (PID {proc.pid})")
        return proc
    except Exception as e:
        log.critical(f"Failed to start {name}: {e}")
        return None


def start_engine():
    print("Starting PolySINT Engine...")
    processes = {}
    notifier = Notifier()
    shutdown_flag = threading.Event()

    try:
        for name in STARTUP_ORDER:
            print(f" -> Launching {name}...")
            proc = _launch_process(name)
            if proc:
                processes[name] = proc
            else:
                print(f" WARNING: Failed to start {name}")

            delay = STARTUP_DELAY.get(name, 1)
            time.sleep(delay)

        print("\nAll systems nominal! PolySINT is fully operational.")
        print("Press [Ctrl + C] to safely shut down all systems.\n")

        notifier.broadcast(
            message="**All PolySINT daemon workers have been successfully launched.**\nAwaiting anomalies and entity movements...",
            title="System Boot: Online"
        )

        last_heartbeat = time.time()

        while not shutdown_flag.is_set():
            time.sleep(5)

            for name, proc in list(processes.items()):
                if proc.poll() is not None:
                    exit_code = proc.returncode
                    log.critical(f"{name} crashed with exit code {exit_code}")
                    print(f"[CRASH] {name} exited (code {exit_code}). Restarting in {WORKER_RESTART_DELAY}s...")

                    notifier.broadcast(
                        message=f"**{name}** crashed (exit code {exit_code}). Attempting auto-restart...",
                        title="Worker Crashed"
                    )

                    time.sleep(WORKER_RESTART_DELAY)
                    new_proc = _launch_process(name)
                    if new_proc:
                        processes[name] = new_proc
                        notifier.broadcast(
                            message=f"**{name}** has been restarted (new PID {new_proc.pid}).",
                            title="Worker Restored"
                        )
                    else:
                        notifier.broadcast(
                            message=f"**{name}** failed to restart. Manual intervention required.",
                            title="Restart Failed"
                        )

            current_time = time.time()
            if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                status_msg = "**Periodic Health Check:**\n"
                all_healthy = True

                for name, p in processes.items():
                    if p.poll() is None:
                        status_msg += f"  **{name}**: Online (PID {p.pid})\n"
                    else:
                        status_msg += f"  **{name}**: Offline (Crashed)\n"
                        all_healthy = False

                title = "System Heartbeat" if all_healthy else "System Degraded"

                print(f"[{datetime.now().strftime('%H:%M:%S')}] Sending Heartbeat...")
                notifier.broadcast(message=status_msg, title=title)

                last_heartbeat = current_time

    except KeyboardInterrupt:
        print("\n\nShutting down PolySINT Engine...")
        shutdown_flag.set()

        notifier.broadcast(message="System was manually shut down by the administrator.", title="System Offline")

        for name, p in processes.items():
            print(f" -> Stopping {name} (PID {p.pid})...")
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print(f"  Force-killing {name}...")
                p.kill()
                p.wait()

        print("Shutdown complete. Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    start_engine()
