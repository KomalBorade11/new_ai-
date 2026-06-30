#!/usr/bin/env python3
import sqlite3

def debug_user_data():
    conn = sqlite3.connect('backend/interview_history.db')
    conn.row_factory = sqlite3.Row
    
    print("=== ALL INTERVIEWS ===")
    all_interviews = conn.execute("SELECT * FROM interviews ORDER BY ended_at DESC").fetchall()
    for interview in all_interviews:
        print(f"ID: {interview['id']}, User: '{interview['user_id']}', Score: {interview['score']}")
    
    print("\n=== USER BREAKDOWN ===")
    users = conn.execute("SELECT user_id, COUNT(*) as count FROM interviews GROUP BY user_id").fetchall()
    for user in users:
        print(f"User: '{user['user_id']}' -> {user['count']} interviews")
    
    print("\n=== AYUSHI_20 SPECIFIC ===")
    ayushi_interviews = conn.execute("SELECT * FROM interviews WHERE user_id = 'ayushi_20' ORDER BY ended_at DESC").fetchall()
    for interview in ayushi_interviews:
        print(f"ID: {interview['id']}, Score: {interview['score']}, Ended: {interview['ended_at']}")
    
    conn.close()

if __name__ == "__main__":
    debug_user_data()
