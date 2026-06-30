import sys
import os

# Add the backend directory to Python path
backend_path = os.path.join(os.path.dirname(__file__), 'backend')
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from utils import speak_text

print('Testing voice functionality...')
speak_text('Hello, this is a test of the college interview system.')
print('Voice test completed.')
