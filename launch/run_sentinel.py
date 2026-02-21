import threading
import time
import uvicorn

# IMPORTANT: adjust this import to match your real engine path
from sentinel_x.engine import SentinelEngine
from api.rork_server import app

engine = SentinelEngine()

def run_engine():
    print("Sentinel X Engine Starting...")
    while True:
        try:
            engine.tick()
            print("Tick complete")
        except Exception as e:
            print("Engine error:", e)
        time.sleep(60)

if __name__ == "__main__":
    engine_thread = threading.Thread(target=run_engine, daemon=True)
    engine_thread.start()

    print("Starting API server on port 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
