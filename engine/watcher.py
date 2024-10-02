import os
import sys
import time
import subprocess
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class ReloadHandler(FileSystemEventHandler):
    def __init__(self, script):
        self.script = script
        self.process = None
        self.restart_script()

    def restart_script(self):
        # Kill the previous process if it exists
        if self.process:
            self.process.kill()

        # Start the new process
        self.process = subprocess.Popen([sys.executable, self.script])
        print(f"Started {self.script}")

    def on_modified(self, event):
        if event.src_path.endswith(self.script):
            print(f"Detected changes in {self.script}. Restarting...")
            self.restart_script()

if __name__ == "__main__":
    script_to_watch = "engine.py"  # Replace with your actual script name
    event_handler = ReloadHandler(script_to_watch)
    observer = Observer()
    observer.schedule(event_handler, path='.', recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()