#!/usr/bin/env python3
"""
Simple Start for AI Mock Interviewer - Bypasses taskkill issues
"""

import socket
import uvicorn
from main import app

def find_free_port():
    """Find a free port starting from 8000."""
    for port in range(8000, 9000):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                if s.connect_ex(('localhost', port)) != 0:
                    return port
        except:
            continue
    return 8000

if __name__ == "__main__":
    print("=== AI Mock Interviewer - Simple Start ===")
    
    # Find port
    port = find_free_port()
    
    print(f"Starting on port {port}")
    print(f"Open: http://localhost:{port}")
    print("Features: Voice Input + Voice Output")
    print("=" * 50)
    
    # Start server
    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    except Exception as e:
        print(f"Error: {e}")
        input("Press Enter to exit...")
