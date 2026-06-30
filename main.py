from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import time
import json
import sqlite3
from graph import analyze_node, question_node, evaluate_node
from utils import (
    extract_resume_text,
    transcribe_audio,
    generate_first_question,
    analyze_answer_and_decide,
    generate_final_feedback,
    generate_final_feedback_structured,
    speak_text
)
import shutil

app = FastAPI()

@app.get("/")
async def read_root():
    """Serve the frontend HTML file."""
    frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    return FileResponse(frontend_path)

@app.get("/frontend/index.html")
async def serve_frontend():
    """Serve the frontend HTML file at the correct path."""
    frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    return FileResponse(frontend_path)

# CORS:
# - Set FRONTEND_ORIGINS as comma-separated URLs in production.
# - Example: FRONTEND_ORIGINS=http://localhost:3000,https://yourdomain.com
raw_origins = os.getenv("FRONTEND_ORIGINS", "").strip()
configured_origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
allow_all_origins = len(configured_origins) == 0

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all_origins else configured_origins,
    allow_credentials=not allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session storage (for demo, use database in production)
sessions = {}
DB_PATH = os.path.join(os.path.dirname(__file__), "interview_history.db")


def _db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _db_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS interviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                resume_text TEXT,
                started_at REAL NOT NULL,
                ended_at REAL,
                score REAL,
                feedback_text TEXT,
                feedback_structured TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS interview_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interview_id INTEGER NOT NULL,
                message_type TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL NOT NULL,
                question_number INTEGER,
                structured TEXT,
                FOREIGN KEY(interview_id) REFERENCES interviews(id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_interviews_user_ended
            ON interviews (user_id, ended_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_interview_timestamp
            ON interview_messages (interview_id, timestamp)
            """
        )
        conn.commit()


def _extract_overall_score(structured_feedback: dict) -> float:
    scores = structured_feedback.get("scores", {}) if isinstance(structured_feedback, dict) else {}
    numeric_scores = []
    for key in ("technical", "communication", "role_readiness"):
        value = scores.get(key)
        if isinstance(value, (int, float)):
            numeric_scores.append(float(value))
    if not numeric_scores:
        return 0.0
    return round(sum(numeric_scores) / len(numeric_scores), 2)


def _create_interview_row(state: dict, session_id: str) -> int:
    with _db_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO interviews (user_id, session_id, role, resume_text, started_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                state.get("user_id", "guest"),
                session_id,
                state.get("role", ""),
                state.get("resume_text", ""),
                state.get("start_time", time.time()),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)

def _complete_abandoned_interviews():
    """Mark interviews as completed if they were abandoned (no end timestamp after 2 hours)."""
    with _db_conn() as conn:
        current_time = time.time()
        two_hours_ago = current_time - (2 * 60 * 60)  # 2 hours in seconds
        
        conn.execute(
            """
            UPDATE interviews 
            SET ended_at = ?, score = 1.0
            WHERE ended_at IS NULL AND started_at < ?
            """,
            (current_time, two_hours_ago)
        )
        conn.commit()


def _save_message(interview_id: int, item: dict):
    if not interview_id:
        return
    with _db_conn() as conn:
        conn.execute(
            """
            INSERT INTO interview_messages (interview_id, message_type, content, timestamp, question_number, structured)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                interview_id,
                item.get("type", ""),
                item.get("content", ""),
                item.get("timestamp", time.time()),
                item.get("question_number"),
                json.dumps(item.get("structured", {})),
            ),
        )
        conn.commit()


def _update_interview_completion(interview_id: int, state: dict, feedback_payload: dict):
    if not interview_id:
        return
    score = _extract_overall_score(feedback_payload.get("structured", {}))
    with _db_conn() as conn:
        conn.execute(
            """
            UPDATE interviews
            SET ended_at = ?, score = ?, feedback_text = ?, feedback_structured = ?
            WHERE id = ?
            """,
            (
                state.get("end_time", time.time()),
                score,
                feedback_payload.get("text", ""),
                json.dumps(feedback_payload.get("structured", {})),
                interview_id,
            ),
        )
        conn.commit()


def _append_chat_item(state: dict, item: dict):
    state["chat_history"].append(item)
    _save_message(state.get("interview_id"), item)


def _normalize_user_id(user_id: str) -> str:
    normalized = (user_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="user_id is required")
    if len(normalized) < 3 or len(normalized) > 100:
        raise HTTPException(status_code=400, detail="user_id must be 3-100 characters")
    return normalized


def _normalize_question(question: str) -> str:
    """Normalize question text for duplicate detection."""
    if not question:
        return ""
    # Remove common prefixes and suffixes, lowercase, strip
    normalized = question.lower().strip()
    prefixes = ["can you", "what is", "how do", "explain", "describe", "tell me about"]
    for prefix in prefixes:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
    # Remove trailing punctuation and extra spaces
    normalized = " ".join(normalized.split())
    return normalized


def _is_unknown_answer(transcript: str) -> bool:
    """Check if the user's answer indicates they don't know the answer."""
    if not transcript:
        return False
    
    unknown_patterns = [
        "i don't know",
        "i dont know", 
        "don't know",
        "dont know",
        "no idea",
        "not sure",
        "not certain",
        "can't say",
        "cant say",
        "i'm not sure",
        "im not sure",
        "i have no idea",
        "no clue"
    ]
    
    transcript_lower = transcript.lower().strip()
    return any(pattern in transcript_lower for pattern in unknown_patterns)


def _get_encouraging_response() -> str:
    """Generate an encouraging response when user doesn't know the answer."""
    import random
    
    encouraging_responses = [
        "Okay, it's okay! Let's move to the next question.",
        "No problem! Let's try a different question.",
        "That's alright! Let's move to the next topic.",
        "Okay, no worries! Let's try another question.",
        "No issue! Let's continue with the next question.",
        "That's fine! Let's move forward to another topic.",
        "Okay, let's try something else then!",
        "No problem at all! Let's go to the next question."
    ]
    
    return random.choice(encouraging_responses)


def _is_duplicate_question(state: dict, question: str) -> bool:
    """Check whether a question has already been asked in this session."""
    normalized = _normalize_question(question)
    if not normalized:
        return True

    for item in state.get("chat_history", []):
        if item.get("type") == "question":
            existing = _normalize_question(item.get("content", ""))
            # Match exact question OR question wrapped with interactive prefix text.
            if existing == normalized or existing.endswith(normalized) or normalized in existing:
                return True
    return False


def _generate_college_first_question(analysis: dict) -> str:
    """Generate first question focused on resume projects for college interview."""
    projects = analysis.get("projects", [])
    if projects:
        first_project = str(projects[0]).strip()
        return f"I saw your project '{first_project}' in your resume. Can you walk me through your end-to-end contribution?"
    
    skills = analysis.get("skills", [])
    if skills:
        return f"I notice you have experience with {skills[0]}. Can you tell me about a project where you used this technology?"
    
    return "Tell me about your academic background and projects you've worked on."


def _get_next_college_question(state: dict) -> str:
    """Return the next college interview question using proper index tracking."""
    questions = state.get("questions", []) or []
    current_index = state.get("current_question_index", 0)
    
    print(f"DEBUG: _get_next_college_question called - index: {current_index}, total questions: {len(questions)}")
    
    # Check if we have more questions available
    if current_index < len(questions):
        next_question = questions[current_index]
        # Update the index for next time
        state["current_question_index"] = current_index + 1
        print(f"DEBUG: Returning question {current_index + 1}: '{next_question[:50]}...'")
        return next_question
    
    print(f"DEBUG: No more questions available")
    return ""


def _build_feedback_payload(state: dict) -> dict:
    """Build both markdown and structured feedback payloads."""
    structured_feedback = generate_final_feedback_structured(state["chat_history"], state["role"])
    text_feedback = generate_final_feedback(state["chat_history"], state["role"])
    return {"text": text_feedback, "structured": structured_feedback}


@app.on_event("startup")
def _startup():
    init_db()
    _complete_abandoned_interviews()

@app.post("/upload_resume")
async def upload_resume(file: UploadFile = File(...), user_id: str = Form(...)):
    """Upload and process resume PDF."""
    try:
        # Validate file type - temporarily allow text files for debugging
        if not (file.filename.lower().endswith('.pdf') or file.filename.lower().endswith('.txt')):
            raise HTTPException(status_code=400, detail="Only PDF and text files are allowed")
        
        # Validate user ID
        if not user_id or len(user_id.strip()) == 0:
            raise HTTPException(status_code=400, detail="User ID is required")
        
        temp_path = f"temp_{file.filename}"
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Handle both PDF and text files
        if file.filename.lower().endswith('.pdf'):
            resume_text = extract_resume_text(temp_path)
        else:
            # For text files, read directly
            with open(temp_path, 'r', encoding='utf-8') as f:
                resume_text = f.read()
        
        os.remove(temp_path)
        
        if not resume_text or len(resume_text.strip()) == 0:
            raise HTTPException(status_code=400, detail="Could not extract text from PDF")
        
        normalized_user_id = _normalize_user_id(user_id)
        session_id = str(time.time())
        sessions[session_id] = {
            "user_id": normalized_user_id,
            "resume_text": resume_text,
            "role": "",
            "chat_history": [],  # Store conversation as list of dicts: {"type": "question"/"answer", "content": "...", "timestamp": ...}
            "start_time": 0,
            "end_time": 0,
            "interview_completed": False,
            "current_topic": "",
            "question_count": 0,
            "max_questions": 16,  # Full college interview with 16 questions
            "analysis": {},
            "questions": [],
            "current_question_index": 0,
            "interview_id": None
        }
        return {
            "session_id": session_id,
            "user_id": sessions[session_id]["user_id"],
            "resume_text": resume_text[:300] + "..."
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.post("/start_interview")
async def start_interview(session_id: str = Form(...)):
    """Start interview for college-level placement system."""
    try:
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        
        state = sessions[session_id]
        # Set fixed role for college system
        state["role"] = "College Student"
        import time as time_module
        state["start_time"] = time_module.time()
        state["interview_id"] = _create_interview_row(state, session_id)
        
        # Initialize question tracking
        state["current_question_index"] = 0
        
        # Analyze resume and generate questions
        from graph import analyze_node
        state = analyze_node(state)
        state = question_node(state)
        
        # Generate first question (resume-focused)
        first_question = _get_next_college_question(state)
        if not first_question or len(first_question.strip()) == 0:
            first_question = _generate_college_first_question(state["analysis"])
        
        # Ensure we have a valid first question
        if not first_question or first_question == "undefined" or len(first_question.strip()) == 0:
            first_question = "Tell me about your academic background and the projects you've worked on."
        
        print(f"First question generated: {first_question[:50]}...")  # Debug log

        # Speak welcome message before first question
        welcome_message = "Welcome to your college placement interview! I'm ready to begin. Let's start with our first question."
        speak_text(welcome_message)
        
        # Small delay to let welcome message finish
        import time
        time.sleep(1)
        
        # Speak the first question aloud
        speak_text(first_question)

        _append_chat_item(state, {
            "type": "question",
            "content": first_question,
            "timestamp": time.time(),
            "question_number": 1
        })
        state["current_topic"] = "resume"
        state["question_count"] = 1
        
        sessions[session_id] = state
        
        return {
            "success": True,
            "chat_history": state["chat_history"],
            "first_question": first_question,
            "current_question": first_question
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting interview: {str(e)}")

@app.post("/process_answer")
async def process_answer(session_id: str = Form(...), transcript: str = Form(...)):
    """Process real-time transcript from speech recognition."""
    try:
        transcript = transcript.strip()
        print(f"DEBUG: Received transcript: '{transcript}' for session: {session_id}")

        if not session_id or session_id not in sessions:
            print(f"DEBUG: Invalid session {session_id}")
            return {"error": "Invalid session"}

        if not transcript:
            print(f"DEBUG: No transcript provided")
            return {"error": "No transcript provided"}

        state = sessions[session_id]
        print(f"DEBUG: State found, current question index: {state.get('current_question_index', 0)}")
        print(f"DEBUG: Total questions available: {len(state.get('questions', []))}")

        # Track elapsed time for context; completion now happens on End Interview action.
        elapsed = time.time() - state["start_time"]

        # Add user answer to chat history
        _append_chat_item(state, {
            "type": "answer",
            "content": transcript,
            "timestamp": time.time()
        })

        # Get the last question for context
        last_question = None
        for item in reversed(state["chat_history"]):
            if item["type"] == "question":
                last_question = item["content"]
                break

        # Simple sequential flow - move to next question in pre-generated list
        response_data = {}
        
        # Check if max questions reached
        if state["question_count"] >= state["max_questions"]:
            # End interview automatically after max questions
            feedback_payload = _build_feedback_payload(state)
            feedback_item = {
                "type": "feedback",
                "content": feedback_payload["text"],
                "structured": feedback_payload["structured"],
                "timestamp": time.time()
            }
            _append_chat_item(state, feedback_item)
            _update_interview_completion(state.get("interview_id"), state, feedback_payload)
            
            response_data["completed"] = True
            response_data["message"] = "Interview completed - maximum questions reached"
            response_data["chat_history"] = state["chat_history"]
            response_data["feedback"] = feedback_payload["text"]
            response_data["feedback_structured"] = feedback_payload["structured"]
        else:
            # Get next question from pre-generated list
            next_question = _get_next_college_question(state)
            print(f"DEBUG: Next question generated: '{next_question}'")
            
            if not next_question:
                print(f"DEBUG: No more questions available, ending interview")
                # End interview if no more questions
                feedback_payload = _build_feedback_payload(state)
                feedback_item = {
                    "type": "feedback",
                    "content": feedback_payload["text"],
                    "structured": feedback_payload["structured"],
                    "timestamp": time.time()
                }
                _append_chat_item(state, feedback_item)
                _update_interview_completion(state.get("interview_id"), state, feedback_payload)
                
                response_data["completed"] = True
                response_data["message"] = "Interview completed"
                response_data["chat_history"] = state["chat_history"]
                response_data["feedback"] = feedback_payload["text"]
                response_data["feedback_structured"] = feedback_payload["structured"]
            else:
                # Check if user said "I don't know" and add encouraging response
                print(f"DEBUG: Checking if transcript is unknown answer: '{transcript}'")
                is_unknown = _is_unknown_answer(transcript)
                print(f"DEBUG: Is unknown answer: {is_unknown}")
                
                if is_unknown:
                    encouraging_msg = _get_encouraging_response()
                    print(f"DEBUG: Generated encouraging message: '{encouraging_msg}'")
                    # Add encouraging message to chat history
                    _append_chat_item(state, {
                        "type": "encouragement",
                        "content": encouraging_msg,
                        "timestamp": time.time()
                    })
                    print(f"DEBUG: Added encouraging response to chat history")
                    print(f"DEBUG: Chat history now has {len(state['chat_history'])} items")
                    print(f"DEBUG: Last item in chat history: {state['chat_history'][-1]}")
                else:
                    print(f"DEBUG: Not an unknown answer, continuing normally")
                
                # Speak the next question aloud
                speak_text(next_question)
                
                _append_chat_item(state, {
                    "type": "question",
                    "content": next_question,
                    "timestamp": time.time(),
                    "question_number": state["question_count"] + 1
                })
                state["question_count"] += 1
                response_data["next_question"] = next_question
                response_data["chat_history"] = state["chat_history"]
                print(f"DEBUG: Response data prepared with next_question: '{next_question}'")

        sessions[session_id] = state
        print(f"DEBUG: Returning response_data: {response_data}")
        return response_data

    except Exception as e:
        print(f"Error processing transcript: {str(e)}")
        return {"error": f"Processing error: {str(e)}"}

@app.post("/end_interview_early")
async def end_interview_early(session_id: str = Form(...)):
    """End interview early and provide feedback."""
    try:
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        
        state = sessions[session_id]
        state["interview_completed"] = True
        state["end_time"] = time.time()
        
        # Speak early closing message
        early_closing_message = "I understand you'd like to end the interview early. Let me generate your feedback based on our conversation so far."
        speak_text(early_closing_message)
        
        # Generate final feedback
        feedback_payload = _build_feedback_payload(state)
        feedback_item = {
            "type": "feedback",
            "content": feedback_payload["text"],
            "structured": feedback_payload["structured"],
            "timestamp": time.time()
        }
        _append_chat_item(state, feedback_item)
        _update_interview_completion(state.get("interview_id"), state, feedback_payload)
        
        sessions[session_id] = state
        
        return {
            "completed": True,
            "message": "Interview ended early",
            "chat_history": state["chat_history"],
            "feedback": feedback_payload["text"],
            "feedback_structured": feedback_payload["structured"]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error ending interview: {str(e)}")

@app.get("/get_chat_history")
async def get_chat_history(session_id: str):
    """Get current chat history."""
    try:
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        
        state = sessions[session_id]
        return {"chat_history": state["chat_history"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.post("/end_interview")
async def end_interview(session_id: str = Form(...)):
    """End interview and get final feedback."""
    try:
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        
        state = sessions[session_id]
        state["end_time"] = time.time()
        
        # Speak closing message
        closing_message = "Thank you for completing the interview! I'm now generating your detailed feedback. Please check your results."
        speak_text(closing_message)
        
        # Generate final feedback if not already provided
        if not any(item["type"] == "feedback" for item in state["chat_history"]):
            feedback_payload = _build_feedback_payload(state)
            feedback_item = {
                "type": "feedback",
                "content": feedback_payload["text"],
                "structured": feedback_payload["structured"],
                "timestamp": time.time()
            }
            _append_chat_item(state, feedback_item)
            _update_interview_completion(state.get("interview_id"), state, feedback_payload)
        
        final_feedback = state["chat_history"][-1]["content"] if state["chat_history"] and state["chat_history"][-1]["type"] == "feedback" else "Interview completed"
        final_feedback_structured = (
            state["chat_history"][-1].get("structured", {})
            if state["chat_history"] and state["chat_history"][-1]["type"] == "feedback"
            else {}
        )
        
        # Clean up session
        del sessions[session_id]
        
        return {
            "completed": True,
            "chat_history": state["chat_history"],
            "final_feedback": final_feedback,
            "final_feedback_structured": final_feedback_structured
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/progress")
@app.get("/get_progress")
async def get_progress(user_id: str):
    """Get all interview attempts and improvement trend for a user."""
    try:
        normalized_user_id = _normalize_user_id(user_id)

        with _db_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, role, started_at, ended_at, score, feedback_structured
                FROM interviews
                WHERE user_id = ? AND ended_at IS NOT NULL
                ORDER BY ended_at ASC
                """,
                (normalized_user_id,),
            ).fetchall()

        attempts = []
        for row in rows:
            structured_feedback = {}
            if row["feedback_structured"]:
                try:
                    structured_feedback = json.loads(row["feedback_structured"])
                except Exception:
                    structured_feedback = {}
            attempts.append(
                {
                    "interview_id": row["id"],
                    "role": row["role"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "score": row["score"] or 0,
                    "scores": structured_feedback.get("scores", {}),
                    "recommendation": structured_feedback.get("recommendation", {}),
                }
            )

        improvement = {
            "has_previous_data": len(attempts) >= 2,
            "latest_score": attempts[-1]["score"] if attempts else 0,
            "previous_score": attempts[-2]["score"] if len(attempts) >= 2 else 0,
            "delta": 0,
            "trend": "no_data",
        }
        if len(attempts) >= 2:
            delta = round((attempts[-1]["score"] or 0) - (attempts[-2]["score"] or 0), 2)
            improvement["delta"] = delta
            improvement["trend"] = "improved" if delta > 0 else ("declined" if delta < 0 else "same")

        return {
            "user_id": normalized_user_id,
            "total_interviews": len(attempts),
            "attempts": attempts,
            "improvement": improvement,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching progress: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)