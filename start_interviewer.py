#!/usr/bin/env python3
"""
Permanent AI Mock Interviewer Server Startup Script
Handles all port conflicts and ensures reliable startup every time.
"""

import socket
import subprocess
import time
import uvicorn
import sys
import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
import shutil

# Import the main app
from main import app

def kill_all_python_processes():
    """Kill all Python processes to ensure clean startup."""
    try:
        print("Cleaning up existing processes...")
        subprocess.run(['taskkill', '/F', '/IM', 'python.exe'], 
                      capture_output=True, check=False)
        time.sleep(2)
    except:
        pass

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

def verify_frontend_exists():
    """Verify frontend file exists."""
    frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    if not os.path.exists(frontend_path):
        print(f"ERROR: Frontend not found at {frontend_path}")
        return False
    print(f"Frontend found: {frontend_path}")
    return True

def verify_tts_dependencies():
    """Verify TTS dependencies are installed."""
    try:
        import pyttsx3
        print("TTS library (pyttsx3) is available")
        return True
    except ImportError:
        print("ERROR: TTS library not installed. Run: pip install pyttsx3")
        return False

def create_fallback_frontend():
    """Create a fallback frontend if original is missing."""
    fallback_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Mock Interviewer</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .container { background: white; border-radius: 20px; box-shadow: 0 20px 40px rgba(0,0,0,0.1); padding: 40px; max-width: 500px; width: 90%; }
        h1 { color: #333; text-align: center; margin-bottom: 10px; font-size: 2em; }
        .subtitle { text-align: center; color: #666; margin-bottom: 30px; font-size: 1.1em; }
        .form-group { margin: 25px 0; }
        label { display: block; margin-bottom: 8px; font-weight: 600; color: #555; }
        input[type="text"], input[type="file"] { width: 100%; padding: 15px; border: 2px solid #e1e1e1; border-radius: 10px; font-size: 16px; transition: all 0.3s; }
        input[type="text"]:focus, input[type="file"]:focus { border-color: #667eea; outline: none; box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1); }
        button { width: 100%; padding: 15px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 10px; font-size: 18px; font-weight: 600; cursor: pointer; transition: all 0.3s; margin-top: 10px; }
        button:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3); }
        button:disabled { background: #ccc; cursor: not-allowed; transform: none; box-shadow: none; }
        .error { color: #e74c3c; text-align: center; margin: 15px 0; padding: 10px; background: #fee; border-radius: 5px; }
        .success { color: #27ae60; text-align: center; margin: 15px 0; padding: 10px; background: #efe; border-radius: 5px; }
        .features { background: #f8f9fa; padding: 20px; border-radius: 10px; margin: 20px 0; }
        .features h3 { color: #333; margin-bottom: 10px; }
        .features ul { list-style: none; padding: 0; }
        .features li { padding: 5px 0; color: #666; }
        .features li:before { content: "â "; color: #27ae60; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h1>AI Mock Interviewer</h1>
        <p class="subtitle">College-Level Interview Practice with Voice</p>
        
        <div class="features">
            <h3>Features:</h3>
            <ul>
                <li>Voice input (speech-to-text)</li>
                <li>Voice output for questions (text-to-speech)</li>
                <li>College-level questions (DSA, SQL, Basics)</li>
                <li>Mixed resume + technical questions</li>
                <li>Adaptive difficulty</li>
                <li>Strict evaluation with scores</li>
            </ul>
        </div>
        
        <div class="form-group">
            <label for="user-id">User ID:</label>
            <input type="text" id="user-id" placeholder="Enter your user ID (e.g., student_01)" required>
        </div>
        
        <div class="form-group">
            <label for="resume-upload">Upload Resume (PDF):</label>
            <input type="file" id="resume-upload" accept=".pdf" required>
        </div>
        
        <button id="start-interview-btn" disabled>Start Interview</button>
        <div id="message" class="error"></div>
    </div>

    <script>
        const userIdInput = document.getElementById('user-id');
        const resumeUpload = document.getElementById('resume-upload');
        const startBtn = document.getElementById('start-interview-btn');
        const messageDiv = document.getElementById('message');

        function checkStartButton() {
            startBtn.disabled = !(userIdInput.value.trim() && resumeUpload.files[0]);
        }

        function showMessage(message, type = 'error') {
            messageDiv.textContent = message;
            messageDiv.className = type;
        }

        userIdInput.addEventListener('input', checkStartButton);
        resumeUpload.addEventListener('change', checkStartButton);

        startBtn.addEventListener('click', async () => {
            const file = resumeUpload.files[0];
            const userId = userIdInput.value.trim();
            
            if (!file || !userId) {
                showMessage('Please fill all fields');
                return;
            }

            if (!file.name.toLowerCase().endsWith('.pdf')) {
                showMessage('Please upload a PDF file');
                return;
            }

            showMessage('Uploading resume...', 'success');
            startBtn.disabled = true;

            const formData = new FormData();
            formData.append('file', file);
            formData.append('user_id', userId);

            try {
                const response = await fetch('/upload_resume', {
                    method: 'POST',
                    body: formData
                });

                const data = await response.json();
                
                if (response.ok) {
                    showMessage('Resume uploaded! Starting interview...', 'success');
                    setTimeout(() => {
                        window.location.href = '/interview?session_id=' + data.session_id;
                    }, 1500);
                } else {
                    showMessage('Upload failed: ' + (data.detail || 'Unknown error'));
                    startBtn.disabled = false;
                }
            } catch (error) {
                showMessage('Network error: ' + error.message);
                startBtn.disabled = false;
            }
        });
    </script>
</body>
</html>
    """
    
    frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
    os.makedirs(frontend_dir, exist_ok=True)
    
    frontend_path = os.path.join(frontend_dir, "index.html")
    with open(frontend_path, 'w', encoding='utf-8') as f:
        f.write(fallback_html)
    
    print(f"Created fallback frontend: {frontend_path}")
    return True

def main():
    """Start the AI Mock Interviewer server with permanent fix."""
    print("=" * 60)
    print("=== AI Mock Interviewer - Permanent Fix Startup ===")
    print("=" * 60)
    
    # Step 1: Clean up existing processes
    kill_all_python_processes()
    
    # Step 2: Kill processes on common ports
    for port in [8000, 8001, 8002, 8003]:
        kill_processes_on_port(port)
        time.sleep(0.5)
    
    # Step 3: Verify dependencies
    if not verify_tts_dependencies():
        print("Please install missing dependencies and try again.")
        return
    
    # Step 4: Verify or create frontend
    if not verify_frontend_exists():
        print("Creating fallback frontend...")
        if not create_fallback_frontend():
            print("ERROR: Could not create frontend.")
            return
    
    # Step 5: Find free port
    port = find_free_port()
    
    if not port:
        print("ERROR: Could not find a free port")
        return
    
    print(f"Starting server on port {port}")
    print(f"Open http://localhost:{port} in your browser")
    print("Features: Voice Input + Voice Output + College-Level Questions")
    print("Press Ctrl+C to stop the server")
    print("=" * 60)
    
    # Step 6: Start server
    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        print(f"Error starting server: {e}")
        print("Trying alternative startup method...")
        
        # Fallback startup
        try:
            uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info", reload=True)
        except Exception as e2:
            print(f"Fallback also failed: {e2}")

if __name__ == "__main__":
    main()
