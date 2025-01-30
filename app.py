import subprocess
import sys
import os
import time
from threading import Thread

def run_streamlit():
    # Run streamlit server
    streamlit_process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "main.py", "--server.port=8501", "--server.address=localhost"])
    return streamlit_process

def main():
    print("Starting SPX Options Trading Dashboard...")
    
    # Start Streamlit in a separate process
    streamlit_process = run_streamlit()
    
    try:
        # Keep the main process running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        streamlit_process.terminate()
        streamlit_process.wait()

if __name__ == "__main__":
    main() 