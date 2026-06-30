#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.dirname(__file__))

from utils import speak_text

print('Testing voice functionality...')
speak_text('Hello, this is a test of the college interview system.')
print('Voice test completed.')
