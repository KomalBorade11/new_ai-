#!/usr/bin/env python3
import sqlite3
import json
from datetime import datetime

def view_database():
    conn = sqlite3.connect('backend/interview_history.db')
    conn.row_factory = sqlite3.Row
    
    print("=== INTERVIEWS TABLE ===")
    interviews = conn.execute("SELECT * FROM interviews ORDER BY ended_at DESC").fetchall()
    for interview in interviews:
        print(f"ID: {interview['id']}")
        print(f"User: {interview['user_id']}")
        print(f"Role: {interview['role']}")
        print(f"Score: {interview['score']}")
        print(f"Started: {datetime.fromtimestamp(interview['started_at'])}")
        print(f"Ended: {datetime.fromtimestamp(interview['ended_at']) if interview['ended_at'] else 'N/A'}")
        print("-" * 50)
    
    print("\n=== MESSAGES TABLE ===")
    messages = conn.execute("SELECT * FROM interview_messages ORDER BY timestamp DESC LIMIT 10").fetchall()
    for msg in messages:
        print(f"Interview ID: {msg['interview_id']}")
        print(f"Type: {msg['message_type']}")
        print(f"Content: {msg['content'][:100]}...")
        print(f"Time: {datetime.fromtimestamp(msg['timestamp'])}")
        print("-" * 30)
    
    conn.close()

if __name__ == "__main__":
    view_database()
