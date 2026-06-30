import socket
import subprocess
import time
import uvicorn
from main import app

def kill_processes_on_port(port):
    """Kill processes using the specified port."""
    try:
        result = subprocess.run(['netstat', '-ano', '|', 'findstr', f':{port}'], 
                              capture_output=True, text=True, shell=True)
        if result.stdout:
            lines = result.stdout.strip().split('\n')
            for line in lines:
                if f':{port}' in line and 'LISTENING' in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        try:
                            subprocess.run(['taskkill', '/F', '/PID', pid], 
                                         capture_output=True, check=True)
                            print(f"Killed process {pid} using port {port}")
                        except:
                            pass
        return True
    except:
        return False

def find_free_port(start_port=8000, max_port=9000):
    """Find a free port in the specified range."""
    for port in range(start_port, max_port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex(('localhost', port))
                if result != 0:
                    return port
        except:
            continue
    return None

def main():
    """Start the server with automatic port management and TTS."""
    print("=== AI Mock Interviewer with TTS Server Startup ===")
    
    # Kill processes on common ports
    for port in [8001, 8002, 8003]:
        kill_processes_on_port(port)
        time.sleep(0.5)
    
    # Find a free port
    port = find_free_port()
    
    if not port:
        print("ERROR: Could not find a free port")
        return
    
    print(f"Starting server on port {port}")
    print(f"Open http://localhost:{port} in your browser")
    print("Features: Voice Input + Voice Output for Questions")
    print("Press Ctrl+C to stop the server")
    print("=" * 60)
    
    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        print(f"Error starting server: {e}")

if __name__ == "__main__":
    main()
