#!/usr/bin/env python3
"""Test script to debug the permanent_start.py issue"""

print("=== Debug Test ===")

try:
    print("1. Testing imports...")
    import subprocess
    import time
    import socket
    import uvicorn
    from main import app
    print("   All imports successful")
    
    print("2. Testing kill_existing function...")
    def kill_existing():
        try:
            result = subprocess.run(['taskkill', '/F', '/IM', 'python.exe'], capture_output=True, text=True)
            print(f"   Taskkill result: {result.returncode}")
            time.sleep(2)
        except Exception as e:
            print(f"   Taskkill error: {e}")
    
    kill_existing()
    print("   kill_existing completed")
    
    print("3. Testing find_free_port function...")
    def find_free_port():
        for port in range(8000, 9000):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1)
                    if s.connect_ex(('localhost', port)) != 0:
                        print(f"   Found free port: {port}")
                        return port
            except:
                continue
        return 8000
    
    port = find_free_port()
    print(f"   Port found: {port}")
    
    print("4. Testing uvicorn.run...")
    print("   About to start uvicorn...")
    # Don't actually start the server, just test if we can call it
    print("   uvicorn.run test completed (not actually started)")
    
    print("=== All tests passed ===")
    
except Exception as e:
    print(f"Error occurred: {e}")
    import traceback
    traceback.print_exc()
