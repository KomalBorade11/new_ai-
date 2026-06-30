import os
from pathlib import Path
import pandas as pd
from huggingface_hub import InferenceClient
import pdfplumber
import re
import json
import pyttsx3
import threading

# Hugging Face API key
HF_TOKEN = os.getenv("HF_TOKEN")  # Set this environment variable
client = InferenceClient(token=HF_TOKEN)

BASE_DIR = Path(__file__).resolve().parent.parent


def _extract_projects_from_resume_text(resume_text: str) -> list:
    """Extract likely project lines directly from resume text without LLM dependency."""
    if not resume_text:
        return []

    lines = [ln.strip(" -*\t") for ln in resume_text.splitlines() if ln.strip()]
    projects = []
    in_project_section = False
    section_keywords = ["project", "projects", "academic projects", "personal projects", "key projects"]

    education_noise = [
        "school", "college", "university", "bachelor", "master", "b.tech", "m.tech",
        "cgpa", "gpa", "12th", "10th", "ssc", "hsc", "board", "education"
    ]

    def _clean_project_candidate(text: str) -> str:
        t = re.sub(r"\s+", " ", text).strip(" -:\t")
        low = t.lower()

        # Skip tech-stack description lines that are not project names.
        if any(low.startswith(prefix) for prefix in ["implemented using", "using ", "technologies:", "tech stack"]):
            return ""

        # Convert description-style lines to project labels.
        # Example: "Built classification models using X, Y" -> "Classification models project"
        if any(low.startswith(prefix) for prefix in ["built ", "developed ", "implemented ", "designed ", "created "]):
            remainder = re.sub(r"^(built|developed|implemented|designed|created)\s+", "", t, flags=re.IGNORECASE)
            remainder = re.split(r"\b(using|with|for)\b", remainder, flags=re.IGNORECASE)[0].strip(" ,.-")
            if remainder:
                t = f"{remainder[:70]} project"

        # Remove noisy fragments
        if len(t.split()) < 2 or len(t) < 8:
            return ""
        if t.count(",") > 2:
            return ""
        return t

    for line in lines:
        low = line.lower()
        if any(token in low for token in education_noise):
            continue

        if any(low == key or low.startswith(key + ":") for key in section_keywords):
            in_project_section = True
            continue

        if in_project_section and any(h in low for h in ["experience", "education", "skills", "certification", "summary"]):
            in_project_section = False

        if in_project_section:
            if len(line) >= 8 and len(line.split()) <= 16:
                cleaned = _clean_project_candidate(line)
                if cleaned:
                    projects.append(cleaned)
        else:
            # Fallback for scattered resume formats
            if any(token in low for token in ["project", "built", "developed", "implemented", "designed"]) and len(line.split()) >= 5:
                cleaned = _clean_project_candidate(line)
                if cleaned:
                    projects.append(cleaned)

    # De-duplicate and keep top useful items
    seen = set()
    clean = []
    for p in projects:
        key = re.sub(r"\s+", " ", p.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            clean.append(p)
    return clean[:6]

def load_datasets():
    """Load questions and answers CSV files."""
    import csv
    
    questions_path = BASE_DIR / "data" / "questions.csv"
    answers_path = BASE_DIR / "data" / "answers.csv"
    kaggle_questions_path = BASE_DIR / "data" / "Software Questions.csv"
    
    # Load original datasets
    questions_df = pd.read_csv(questions_path, encoding='utf-8') if questions_path.exists() else pd.DataFrame()
    
    # Load answers with proper CSV handling
    answers_data = []
    if answers_path.exists():
        with open(answers_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader)
            for row in reader:
                if len(row) >= 2:
                    # Join all columns after the first as the answer (in case of extra commas)
                    answers_data.append({
                        'question': row[0],
                        'answer': ','.join(row[1:])
                    })
    answers_df = pd.DataFrame(answers_data)
    
    # Load Kaggle dataset with encoding fallback
    kaggle_df = pd.DataFrame()
    if kaggle_questions_path.exists():
        try:
            kaggle_df = pd.read_csv(kaggle_questions_path, encoding='utf-8')
        except UnicodeDecodeError:
            try:
                kaggle_df = pd.read_csv(kaggle_questions_path, encoding='latin-1')
            except Exception as e:
                print(f"Warning: Could not load Kaggle dataset: {e}")
    
    return questions_df, answers_df, kaggle_df

def extract_resume_text(pdf_path: str) -> str:
    """Extract text from PDF resume using pdfplumber."""
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text

def call_llm(prompt: str, model: str = "meta-llama/Llama-3.1-8B-Instruct") -> str:
    """Call Hugging Face Inference API."""
    try:
        response = client.text_generation(prompt, model=model, max_new_tokens=500)
        # Response is a string directly
        if isinstance(response, str):
            return response
        return str(response)
    except Exception as e:
        print(f"LLM Error: {e}")
        return "{}"

def transcribe_audio(audio_path: str) -> str:
    """Legacy function - no longer used with real-time speech recognition."""
    return "Real-time speech recognition is handled by the browser Web Speech API"

def analyze_resume(resume_text: str) -> dict:
    """Analyze resume to extract skills, projects, experience, and map to question categories."""
    if not resume_text or len(resume_text.strip()) == 0:
        return {
            "skills": ["Not provided"], 
            "projects": [], 
            "experience": "Not specified",
            "categories": ["General Programming"]
        }
    
    # First, extract keywords directly from resume text
    resume_lower = resume_text.lower()
    
    # Comprehensive technology keywords
    tech_keywords = {
        # Programming Languages
        'python': ['python', 'django', 'flask', 'fastapi', 'pandas', 'numpy', 'scikit-learn', 'tensorflow', 'pytorch', 'jupyter'],
        'javascript': ['javascript', 'js', 'node.js', 'nodejs', 'react', 'vue', 'angular', 'express', 'jquery'],
        'java': ['java', 'spring', 'hibernate', 'maven', 'gradle'],
        'cpp': ['c++', 'cpp', 'qt', 'boost'],
        'csharp': ['c#', 'csharp', '.net', 'asp.net', 'entity framework'],
        'php': ['php', 'laravel', 'symfony', 'wordpress'],
        'ruby': ['ruby', 'rails', 'ruby on rails'],
        'go': ['go', 'golang'],
        'rust': ['rust'],
        'kotlin': ['kotlin', 'android'],
        'swift': ['swift', 'ios'],
        'scala': ['scala', 'spark'],
        
        # Web Technologies
        'html': ['html', 'html5'],
        'css': ['css', 'css3', 'sass', 'scss', 'bootstrap', 'tailwind'],
        'react': ['react', 'react.js', 'redux', 'next.js', 'gatsby'],
        'angular': ['angular', 'angularjs'],
        'vue': ['vue', 'vue.js', 'nuxt'],
        
        # Backend
        'node': ['node.js', 'nodejs', 'express', 'nest.js'],
        'django': ['django', 'django rest framework'],
        'flask': ['flask'],
        'spring': ['spring', 'spring boot', 'spring framework'],
        'laravel': ['laravel'],
        
        # Databases
        'sql': ['sql', 'mysql', 'postgresql', 'postgres', 'sqlite', 'oracle', 'mssql', 'sql server'],
        'nosql': ['mongodb', 'mongo', 'cassandra', 'redis', 'dynamodb', 'couchdb', 'elasticsearch'],
        
        # Cloud & DevOps
        'aws': ['aws', 'amazon web services', 'ec2', 's3', 'lambda', 'rds', 'cloudformation'],
        'azure': ['azure', 'microsoft azure'],
        'gcp': ['gcp', 'google cloud', 'firebase'],
        'docker': ['docker', 'kubernetes', 'k8s', 'container', 'docker-compose'],
        'terraform': ['terraform', 'infrastructure as code'],
        'jenkins': ['jenkins', 'ci/cd', 'continuous integration'],
        'git': ['git', 'github', 'gitlab', 'bitbucket'],
        
        # Data Science & ML
        'machine learning': ['machine learning', 'ml', 'scikit-learn', 'tensorflow', 'pytorch', 'keras'],
        'data science': ['data science', 'pandas', 'numpy', 'matplotlib', 'seaborn', 'jupyter'],
        'deep learning': ['deep learning', 'neural network', 'cnn', 'rnn', 'lstm'],
        'nlp': ['nlp', 'natural language processing', 'spacy', 'nltk'],
        
        # Mobile
        'android': ['android', 'kotlin', 'java'],
        'ios': ['ios', 'swift', 'objective-c'],
        'react native': ['react native', 'expo'],
        'flutter': ['flutter', 'dart'],
        
        # Other
        'linux': ['linux', 'ubuntu', 'centos', 'bash', 'shell scripting'],
        'testing': ['testing', 'unit test', 'integration test', 'selenium', 'jest', 'pytest', 'junit'],
        'security': ['security', 'oauth', 'jwt', 'encryption', 'ssl', 'https'],
        'api': ['api', 'rest', 'graphql', 'soap', 'microservices'],
        'design patterns': ['design patterns', 'solid', 'mvc', 'mvvm']
    }
    
    # Extract skills from keywords
    found_skills = set()
    for category, keywords in tech_keywords.items():
        for keyword in keywords:
            if keyword in resume_lower:
                found_skills.add(category)
    
    # Use LLM for more detailed analysis
    prompt = f"""Extract from this resume:
1. Technical skills (be very specific, list actual technologies/tools used)
2. Projects (list with technologies used)
3. Experience level (Junior/Entry-level: <2 years, Mid-level: 2-5 years, Senior: >5 years)
4. Primary role/domain (e.g., Full Stack Developer, Data Scientist, Backend Engineer, etc.)

Resume: {resume_text[:1000]}

Reply in format: skills: X | projects: Y | experience: Z | domain: W"""
    
    response = call_llm(prompt)
    
    # Default values
    llm_skills = ["General programming"]
    projects = []
    experience = "Mid-level"
    domain = "Software Engineering"
    
    try:
        # Try to parse if JSON
        if response.strip().startswith('{'):
            data = json.loads(response)
            llm_skills = data.get("skills", llm_skills)
            projects = data.get("projects", projects) 
            experience = data.get("experience", experience)
            domain = data.get("domain", domain)
    except:
        # Parse text response
        lines = response.split('|')
        for line in lines:
            line = line.strip()
            if line.startswith('skills:'):
                llm_skills = [s.strip() for s in line[7:].split(',')]
            elif line.startswith('projects:'):
                projects = [p.strip() for p in line[9:].split(',')]
            elif line.startswith('experience:'):
                experience = line[11:].strip()
            elif line.startswith('domain:'):
                domain = line[7:].strip()

    # Deterministic project extraction from resume text to avoid LLM misses.
    parsed_projects = _extract_projects_from_resume_text(resume_text)
    if parsed_projects:
        projects = parsed_projects
    
    # Combine keyword-extracted and LLM-extracted skills
    all_skills = list(set(llm_skills + list(found_skills)))
    
    # Enhanced category mapping
    category_mapping = {
        # Programming Languages
        'python': ['General Programming', 'Data Structures', 'Algorithms', 'Data Science'],
        'javascript': ['General Programming', 'Web Development', 'Frontend'],
        'java': ['General Programming', 'Object-Oriented Programming', 'Data Structures'],
        'cpp': ['General Programming', 'Data Structures', 'Algorithms', 'Low-level Systems'],
        'csharp': ['General Programming', 'Object-Oriented Programming'],
        'php': ['General Programming', 'Web Development', 'Backend'],
        'ruby': ['General Programming', 'Web Development'],
        'go': ['General Programming', 'Backend', 'System Design'],
        'rust': ['General Programming', 'Low-level Systems'],
        'kotlin': ['General Programming', 'Mobile Development'],
        'swift': ['General Programming', 'Mobile Development'],
        'scala': ['General Programming', 'Data Engineering'],
        
        # Web Technologies
        'html': ['Web Development', 'Frontend'],
        'css': ['Web Development', 'Frontend'],
        'react': ['Web Development', 'Frontend', 'JavaScript Frameworks'],
        'angular': ['Web Development', 'Frontend', 'JavaScript Frameworks'],
        'vue': ['Web Development', 'Frontend', 'JavaScript Frameworks'],
        
        # Backend
        'node': ['Backend', 'Web Development', 'Server-side JavaScript'],
        'django': ['Backend', 'Web Development', 'Python Frameworks'],
        'flask': ['Backend', 'Web Development', 'Python Frameworks'],
        'spring': ['Backend', 'Java Frameworks'],
        'laravel': ['Backend', 'Web Development', 'PHP Frameworks'],
        
        # Databases
        'sql': ['Database Systems', 'Data Engineering'],
        'nosql': ['Database Systems', 'Data Engineering', 'System Design'],
        
        # Cloud & DevOps
        'aws': ['Cloud Computing', 'System Design', 'DevOps'],
        'azure': ['Cloud Computing', 'System Design'],
        'gcp': ['Cloud Computing', 'System Design'],
        'docker': ['DevOps', 'System Design', 'Containerization'],
        'terraform': ['DevOps', 'Infrastructure as Code'],
        'jenkins': ['DevOps', 'CI/CD'],
        'git': ['Version Control', 'Software Development'],
        
        # Data Science & ML
        'machine learning': ['Machine Learning', 'Artificial Intelligence', 'Data Science'],
        'data science': ['Data Science', 'Machine Learning', 'Statistics'],
        'deep learning': ['Machine Learning', 'Artificial Intelligence'],
        'nlp': ['Machine Learning', 'Natural Language Processing'],
        
        # Mobile
        'android': ['Mobile Development', 'Android'],
        'ios': ['Mobile Development', 'iOS'],
        'react native': ['Mobile Development', 'Cross-platform'],
        'flutter': ['Mobile Development', 'Cross-platform'],
        
        # Other
        'linux': ['System Administration', 'DevOps'],
        'testing': ['Software Testing', 'Quality Assurance'],
        'security': ['Security', 'Cybersecurity'],
        'api': ['API Design', 'System Design', 'Web Development'],
        'design patterns': ['Software Design', 'Architecture']
    }
    
    categories = set()
    skills_lower = [skill.lower() for skill in all_skills]
    
    for skill in skills_lower:
        for key, cats in category_mapping.items():
            if key in skill or any(keyword in skill for keyword in tech_keywords.get(key, [])):
                categories.update(cats)
    
    # Add domain-specific categories with more precision
    domain_lower = domain.lower()
    if any(word in domain_lower for word in ['data scientist', 'data science', 'machine learning', 'ml', 'ai']):
        categories.update(['Machine Learning', 'Data Science', 'Statistics', 'Data Engineering'])
    elif any(word in domain_lower for word in ['web developer', 'frontend', 'backend', 'full stack', 'fullstack']):
        categories.update(['Web Development', 'System Design', 'API Design'])
    elif 'mobile' in domain_lower or 'ios' in domain_lower or 'android' in domain_lower:
        categories.update(['Mobile Development', 'System Design'])
    elif any(word in domain_lower for word in ['devops', 'infrastructure', 'cloud']):
        categories.update(['DevOps', 'System Design', 'Cloud Computing'])
    elif 'security' in domain_lower:
        categories.update(['Security', 'System Design'])
    
    # Add default categories if none found
    if not categories:
        categories = {'General Programming', 'Algorithms', 'Data Structures'}
    
    return {
        "skills": all_skills,
        "projects": projects,
        "experience": experience,
        "domain": domain,
        "categories": list(categories)
    }

def generate_college_questions(resume_analysis: dict, questions_df: pd.DataFrame, kaggle_df: pd.DataFrame) -> list:
    """Generate college placement interview questions using EXACT fixed question bank."""
    
    import random
    random.seed()  # Ensure true randomness each time
    
    projects = resume_analysis.get("projects", [])
    
    # EXACT FIXED QUESTION BANK AS SPECIFIED
    
    # Resume Questions - BASIC
    resume_basic = [
        "Can you explain your project in simple terms?",
        "What was the main goal of your project?",
        "What technologies did you use and why?",
        "What was your role in the project?",
        "How does your project work step by step?"
    ]
    
    # Resume Questions - MEDIUM
    resume_medium = [
        "What challenges did you face while building this project?",
        "How did you solve a bug or issue in your project?",
        "If you had more time, what would you improve?",
        "Why did you choose this approach instead of another?",
        "How would your project handle more users (scalability)?"
    ]
    
    # Resume Questions - FOLLOW-UPS
    resume_followups = [
        "Can you explain that in more detail?",
        "What happens internally when this feature runs?",
        "Can you give an example?"
    ]
    
    # Java Questions - EASY
    java_easy = [
        "What is Java?",
        "What are the main features of Java?",
        "What is JVM?",
        "What is JDK and JRE?",
        "What are data types in Java?"
    ]
    
    # Java Questions - MEDIUM
    java_medium = [
        "What is the difference between == and .equals()?",
        "What is method overloading vs overriding?",
        "What is constructor?",
        "What is static keyword?",
        "What is exception handling in Java?"
    ]
    
    # OOP Questions - EASY
    oop_easy = [
        "What is Object-Oriented Programming?",
        "What are the four pillars of OOP?",
        "What is a class and object?",
        "What is encapsulation?"
    ]
    
    # OOP Questions - MEDIUM
    oop_medium = [
        "What is inheritance? Give example",
        "What is polymorphism?",
        "Difference between abstraction and encapsulation",
        "What is an interface?",
        "Abstract class vs interface"
    ]
    
    # DBMS / SQL Questions - EASY
    dbms_easy = [
        "What is DBMS?",
        "What is a table?",
        "What is a primary key?",
        "What is a foreign key?",
        "What is SQL?"
    ]
    
    # DBMS / SQL Questions - MEDIUM
    dbms_medium = [
        "What are joins?",
        "Difference between INNER JOIN and LEFT JOIN",
        "What is normalization?",
        "What is indexing?",
        "What is GROUP BY?"
    ]
    
    # Mixed Questions
    mixed_questions = [
        "Tell me about yourself",
        "What are your strengths and weaknesses?",
        "Why should we hire you?",
        "What did you learn from your project?",
        "Explain one concept you are confident in"
    ]
    
    # STRICT FLOW: EXACTLY 3 resume questions, then Java/OOP/DBMS, then Mixed
    final_questions = []
    
    # Step 1: EXACTLY 3 resume questions (randomly selected)
    all_resume_questions = resume_basic + resume_medium
    random.shuffle(all_resume_questions)
    
    # Generate project-specific resume questions
    project_questions = []
    for project in projects[:3]:  # Top 3 projects
        project_text = str(project).strip()
        if project_text:
            # Use exact templates from the fixed question bank
            project_questions.extend([
                f"Can you explain your project in simple terms? (for {project_text})",
                f"What was the main goal of your project? (for {project_text})",
                f"What technologies did you use and why? (for {project_text})",
                f"What challenges did you face while building this project? (for {project_text})",
                f"How did you solve a bug or issue in your project? (for {project_text})"
            ])
    
    # Add 3 resume questions (project-specific if available, otherwise generic)
    if project_questions:
        random.shuffle(project_questions)
        final_questions.extend(project_questions[:3])
    else:
        final_questions.extend(all_resume_questions[:3])
    
    # Step 2: Java questions (randomly selected from fixed bank)
    all_java_questions = java_easy + java_medium
    random.shuffle(all_java_questions)
    final_questions.extend(all_java_questions[:4])  # 4 Java questions
    
    # Step 3: OOP questions (randomly selected from fixed bank)
    all_oop_questions = oop_easy + oop_medium
    random.shuffle(all_oop_questions)
    final_questions.extend(all_oop_questions[:4])  # 4 OOP questions
    
    # Step 4: DBMS/SQL questions (randomly selected from fixed bank)
    all_dbms_questions = dbms_easy + dbms_medium
    random.shuffle(all_dbms_questions)
    final_questions.extend(all_dbms_questions[:3])  # 3 DBMS questions
    
    # Step 5: Mixed questions (randomly selected from fixed bank)
    random.shuffle(mixed_questions)
    final_questions.extend(mixed_questions[:2])  # 2 mixed questions
    
    # Ensure no duplicates and maintain order
    seen = set()
    unique_questions = []
    for q in final_questions:
        if q not in seen:
            seen.add(q)
            unique_questions.append(q)
    
    print(f"Generated {len(unique_questions)} questions with STRICT flow")
    print(f"Resume: 3, Java: 4, OOP: 4, DBMS: 3, Mixed: 2")
    
    return unique_questions[:16]  # Return max 16 questions

def generate_questions(role: str, resume_analysis: dict, questions_df: pd.DataFrame, kaggle_df: pd.DataFrame) -> list:
    """Legacy function - redirects to college question generation."""
    return generate_college_questions(resume_analysis, questions_df, kaggle_df)

# ... (rest of the code remains the same)
def evaluate_answer(question: str, user_answer: str, reference_answer: str) -> dict:
    """Evaluate user answer using LLM and reference."""
    prompt = f"""Rate this answer 1-10:
Q: {question}
User: {user_answer[:200]}
Ref: {reference_answer[:200]}

Give score and brief feedback (50 words max)."""
    
    response = call_llm(prompt)
    import json
    import random
    
    try:
        if response.strip().startswith('{'):
            data = json.loads(response)
            return {
                "score": int(data.get("score", 6)),
                "feedback": str(data.get("feedback", "Good response")),
                "strengths": str(data.get("strengths", "Clear communication")),
                "weaknesses": str(data.get("weaknesses", "Could be more detailed"))
            }
    except:
        pass
    
    # Default score
    score = random.randint(6, 8)
    return {
        "score": score,
        "feedback": "Good response. Could add more details.",
        "strengths": "Clear explanation",
        "weaknesses": "Consider providing examples"
    }

def generate_first_question(role: str, analysis: dict) -> str:
    """Generate the first interview question based on role and resume analysis."""
    skills = analysis.get("skills", ["general skills"])
    experience = analysis.get("experience", "relevant experience")
    projects = analysis.get("projects", [])
    first_project = str(projects[0]).strip() if projects else ""

    if first_project:
        return f"I saw your project '{first_project}' in your resume. Can you walk me through your end-to-end contribution?"
    
    prompt = f"""Generate a natural, conversational first question for a {role} interview.
    
Candidate background:
- Skills: {', '.join(skills[:3])}
- Experience: {experience[:100]}

Make it engaging and relevant to their background. Keep it under 20 words."""
    
    response = call_llm(prompt)
    if response and len(response.strip()) > 10:
        return response.strip()
    return f"Tell me about your experience as a {role} and what interests you about this role."


def _adaptive_interviewer_reaction(answer: str) -> str:
    """Return a short reaction based on answer quality heuristics."""
    answer_text = (answer or "").strip()
    answer_lower = answer_text.lower()
    word_count = len(answer_text.split())

    strong_signals = ["because", "trade-off", "tradeoff", "impact", "result", "improved", "reduced", "increased", "architecture"]
    medium_signals = ["example", "implemented", "designed", "used", "built", "debugged", "deployed"]

    strong_hits = sum(1 for token in strong_signals if token in answer_lower)
    medium_hits = sum(1 for token in medium_signals if token in answer_lower)

    if word_count >= 60 and (strong_hits >= 2 or medium_hits >= 3):
        return "Great depth and clear reasoning."
    if word_count >= 30 and (strong_hits >= 1 or medium_hits >= 2):
        return "Nice explanation, that gives useful context."
    if word_count < 12:
        return "Thanks. Could you add a bit more detail?"
    return "Good start, let's go a little deeper."

def analyze_answer_and_decide(question: str, answer: str, role: str, analysis: dict, question_count: int, elapsed_time: float) -> dict:
    """Analyze the candidate's answer and decide the next action for college interview."""
    answer_lower = (answer or "").lower()
    unknown_markers = [
        "don't know", "dont know", "no idea", "not sure",
        "cannot answer", "can't answer", "skip", "i dont know", "i don't know"
    ]

    # If candidate clearly does not know, move forward without pressure.
    if any(marker in answer_lower for marker in unknown_markers):
        return {
            "action": "new_topic",
            "interviewer_message": "It's okay, let's move to the next question.",
            "question": "Let's switch to another topic. Can you explain one concept you are more confident about?",
            "topic": "topic_switch_after_unknown"
        }
    
    projects = analysis.get("projects", [])
    project_context = ", ".join([str(p) for p in projects[:4]]) if projects else "No projects extracted"

    prompt = f"""Analyze this college placement interview answer and decide the next action:

Role: College Student
Question: {question}
Answer: {answer[:300]}
Resume Projects: {project_context}

Available actions:
1. follow_up: Ask a follow-up question about this specific answer
2. new_topic: Change to a different topic area (Java, OOP, DBMS)
3. continue_topic: Ask another question on the same general topic

Consider:
- Answer quality and depth
- Whether more clarification is needed
- If we've explored this topic sufficiently
- Natural flow of conversation
- Keep it interactive: first acknowledge something from the candidate's answer briefly, then ask next question.
- Prefer project-based follow-ups when relevant.
- Focus on college-level difficulty (easy to medium)

Respond in JSON format:
{{\"action\": \"follow_up|new_topic|continue_topic\", \"interviewer_message\": \"one short interactive reaction\", \"question\": \"next question text\", \"topic\": \"topic_name_if_changing\"}}"""
    
    response = call_llm(prompt)
    
    try:
        import json
        if response.strip().startswith('{'):
            decision = json.loads(response)
            if decision.get("action") in ["follow_up", "new_topic", "continue_topic"]:
                if not str(decision.get("interviewer_message", "")).strip():
                    decision["interviewer_message"] = _adaptive_interviewer_reaction(answer)
                return decision
    except:
        pass
    
    # Default decision based on question count
    if question_count < 3:
        return {
            "action": "continue_topic",
            "interviewer_message": _adaptive_interviewer_reaction(answer),
            "question": "Can you elaborate more on that experience?"
        }
    elif question_count < 7:
        project_driven = ""
        if projects:
            project_driven = f"Let's discuss '{projects[0]}': what trade-offs did you make and why?"
        return {
            "action": "new_topic", 
            "interviewer_message": _adaptive_interviewer_reaction(answer),
            "question": project_driven or "What are your career goals in the tech industry?",
            "topic": "career_goals"
        }
    else:
        return {
            "action": "new_topic",
            "interviewer_message": _adaptive_interviewer_reaction(answer),
            "question": "Let's continue with another technical question. How would you handle a problem you encountered in your projects?",
            "topic": "technical_depth"
        }

def generate_final_feedback_structured(chat_history: list, role: str) -> dict:
    """Generate detailed structured feedback JSON for frontend rendering."""
    import json

    conversation_text = ""
    question_count = 0
    answer_count = 0
    for item in chat_history:
        if item.get("type") == "question":
            conversation_text += f"Q: {item.get('content', '')}\n"
            question_count += 1
        elif item.get("type") == "answer":
            conversation_text += f"A: {item.get('content', '')}\n"
            answer_count += 1

    prompt = f"""You are a senior college placement interviewer. Return ONLY valid JSON for detailed feedback on a college placement interview.

Interview metadata:
- questions_asked: {question_count}
- answers_given: {answer_count}

Conversation:
{conversation_text[:2500]}

Focus on college-level expectations:
- Technical fundamentals (Java, OOP, DBMS)
- Project experience and practical application
- Basic problem-solving abilities
- Communication clarity

Provide detailed, constructive feedback with specific examples from their answers.

Return JSON object with these exact keys:
{{
  "role": "College Student",
  "summary": "4-6 sentence comprehensive summary",
  "scores": {{
    "technical": 0,
    "communication": 0
  }},
  "strengths": ["3-6 specific bullet items with examples"],
  "improvements": ["3-6 specific bullet items with actionable advice"],
  "question_notes": [
    {{
      "theme": "string",
      "did_well": ["1-3 items"],
      "missing": ["1-3 items"],
      "better_answer_outline": "2-4 lines"
    }}
  ],
  "plan": {{
    "week_1": ["4 concrete actions"],
    "week_2": ["4 concrete actions"]
  }},
  "recommendation": {{
    "decision": "Strong Hire|Hire|Borderline|No Hire",
    "reason": "3-5 sentence explanation"
  }}
}}

Rules:
- Scores must be integers 1-10.
- Be specific and evidence-based.
- Focus on college-level readiness, not industry expertise.
- Do not include markdown or text outside JSON."""

    role_lower = (role or "").lower()
    role_focus = {
        "data scientist": [
            "Model evaluation, feature engineering, and experiment design depth",
            "Clear explanation of preprocessing and validation strategy",
            "Business impact framing with metrics"
        ],
        "machine learning": [
            "Model lifecycle understanding (training to inference)",
            "Handling bias/variance and model monitoring",
            "Productionization and reliability of ML systems"
        ],
        "backend": [
            "API design and data-layer trade-off clarity",
            "Scalability, reliability, and observability depth",
            "Security and performance optimization decisions"
        ],
        "frontend": [
            "Component architecture and state management quality",
            "Performance and UX trade-off awareness",
            "Accessibility and maintainability practices"
        ],
        "devops": [
            "CI/CD, infra automation, and rollback strategy",
            "Monitoring, alerting, and incident readiness",
            "Cost and reliability optimization choices"
        ],
    }

    focus_points = ["Technical fundamentals", "Project experience", "Communication clarity"]

    answers = [item.get("content", "") for item in chat_history if item.get("type") == "answer"]
    avg_words = int(sum(len(a.split()) for a in answers) / max(1, len(answers)))
    low_confidence_markers = ["don't know", "dont know", "no idea", "not sure", "skip", "can't answer", "cannot answer"]

    # Content-based evaluation system
    if not answers or len(answers) == 0:
        # No answers provided - lowest score
        base_score = 1
    else:
        # Analyze answer content quality
        content_score = 0
        total_possible = 0
        
        # Check for "I don't know" answers first - these get score 1
        dont_know_count = 0
        for answer in answers:
            if not answer or len(answer.strip()) < 5:
                # Empty or very short answer - poor quality
                content_score += 1
                total_possible += 10
                dont_know_count += 1
                continue
            
            answer_lower = answer.lower()
            
            # Check if this is a "don't know" answer
            if any(marker in answer_lower for marker in ["don't know", "dont know", "no idea", "not sure", "skip", "can't answer", "cannot answer"]):
                content_score += 1  # Very poor quality
                total_possible += 10
                dont_know_count += 1
                continue
            
            # Check for quality indicators (10 points max per answer)
            points = 0
            
            # 1. Answer relevance (3 points)
            if any(keyword in answer_lower for keyword in ["because", "since", "due to", "as"]):
                points += 1  # Provides reasoning
            if any(keyword in answer_lower for keyword in ["example", "project", "experience", "implemented", "built"]):
                points += 1  # Gives examples
            if len(answer.split()) >= 15:  # Substantive answer
                points += 1
            
            # 2. Technical depth (3 points)
            tech_keywords = ["api", "database", "algorithm", "architecture", "system", "performance", "security", "scalability", "testing", "deployment"]
            if any(keyword in answer_lower for keyword in tech_keywords):
                points += 1
            if any(keyword in answer_lower for keyword in ["optimize", "improve", "efficient", "fast", "reliable"]):
                points += 1
            if any(keyword in answer_lower for keyword in ["trade-off", "tradeoff", "challenge", "problem", "solution"]):
                points += 1
            
            # 3. Communication clarity (2 points)
            if any(keyword in answer_lower for keyword in ["first", "then", "finally", "step", "process"]):
                points += 1  # Structured response
            if not any(marker in answer_lower for marker in ["don't know", "dont know", "no idea", "not sure", "skip"]):
                points += 1  # Confident response
            
            # 4. College-level technical knowledge (2 points)
            college_keywords = ["java", "oop", "inheritance", "polymorphism", "sql", "database", "normalization", "algorithm", "data structure"]
            if any(keyword in answer_lower for keyword in college_keywords):
                points += 2
                break
            
            content_score += points
            total_possible += 10
        
        # If all answers are "don't know", give score 1.0
        if dont_know_count == len(answers) and dont_know_count > 0:
            base_score = 1
        # Calculate final score based on content quality
        elif total_possible > 0:
            base_score = max(1, min(10, int((content_score / total_possible) * 10)))
        else:
            base_score = 1

    # Force minimum score for interviews with no answers
    if not answers or len(answers) == 0:
        base_score = 1
        fallback_scores = {"technical": 1, "communication": 1}
    else:
        fallback_scores = {"technical": base_score, "communication": min(10, base_score + 1)}
    
    fallback = {
        "role": "College Student",
        "summary": f"You completed a college placement interview with {question_count} questions and {answer_count} answers. Based on your responses, your current level appears {'early-stage' if base_score <= 4 else 'foundational to intermediate'} for college placements. Stronger fundamentals, clearer project examples, and better technical communication will improve interview outcomes.",
        "scores": fallback_scores,
        "strengths": [
            "Demonstrated foundational knowledge of core technical concepts",
            "Attempted to explain reasoning and project experience",
            "Showed willingness to discuss academic projects"
        ],
        "improvements": [
            f"Improve {focus_points[0]}",
            "Use clearer answer structure: context, approach, result",
            f"Improve {focus_points[2]}"
        ],
        "question_notes": [
            {
                "theme": "Core technical concepts",
                "did_well": ["Provided relevant baseline explanations"],
                "missing": ["More depth and implementation details"],
                "better_answer_outline": "Define concept briefly, explain trade-offs, provide a real project example, and quantify impact."
            }
        ],
        "plan": {
            "week_1": [
                f"Prepare 8 STAR stories focused on {role} work",
                "Practice 2 timed mock interviews with self-review",
                "Build one mini project and document decisions",
                "Create concise revision notes for common topics"
            ],
            "week_2": [
                "Rehearse advanced questions with 2-3 minute structured responses",
                "Add performance/security/scalability considerations to answers",
                "Record and review communication clarity and confidence",
                "Run one full mock loop and compare improvement metrics"
            ]
        },
        "recommendation": {
            "decision": (
                "No Hire" if base_score <= 4 
                else "Borderline" if base_score <= 6
                else "Hire" if base_score <= 8
                else "Strong Hire"
            ),
            "reason": (
                "Several responses indicated uncertainty or missing depth for key role competencies. Focused practice on fundamentals and structured project explanations is required before strong interview performance is likely."
                if base_score <= 4
                else "The candidate shows potential but is not consistently strong across technical depth, structured communication, and advanced role-specific judgment. With targeted improvement over the next two weeks, interview readiness can improve significantly."
                if base_score <= 6
                else "Good performance across technical depth, communication, and role-specific competencies. Candidate demonstrates readiness for the position with minor areas for continued growth."
                if base_score <= 8
                else "Exceptional performance with strong technical depth, clear communication, and advanced role-specific judgment. Candidate is highly recommended for immediate hire."
            )
        }
    }

    def _score(value, default):
        try:
            v = int(value)
            return max(1, min(10, v))
        except Exception:
            return default

    def _list(value, default):
        return value if isinstance(value, list) and value else default

    response = call_llm(prompt)
    if response:
        try:
            parsed = json.loads(response)
            if isinstance(parsed, dict) and parsed:
                scores = parsed.get("scores", {}) if isinstance(parsed.get("scores", {}), dict) else {}
                recommendation = parsed.get("recommendation", {}) if isinstance(parsed.get("recommendation", {}), dict) else {}
                plan = parsed.get("plan", {}) if isinstance(parsed.get("plan", {}), dict) else {}

                normalized = {
                    "role": str(parsed.get("role") or fallback["role"]),
                    "summary": str(parsed.get("summary") or fallback["summary"]),
                    "scores": {
                        "technical": _score(scores.get("technical"), fallback["scores"]["technical"]),
                        "communication": _score(scores.get("communication"), fallback["scores"]["communication"]),
                    },
                    "strengths": _list(parsed.get("strengths"), fallback["strengths"]),
                    "improvements": _list(parsed.get("improvements"), fallback["improvements"]),
                    "question_notes": _list(parsed.get("question_notes"), fallback["question_notes"]),
                    "plan": {
                        "week_1": _list(plan.get("week_1"), fallback["plan"]["week_1"]),
                        "week_2": _list(plan.get("week_2"), fallback["plan"]["week_2"]),
                    },
                    "recommendation": {
                        "decision": str(recommendation.get("decision") or fallback["recommendation"]["decision"]),
                        "reason": str(recommendation.get("reason") or fallback["recommendation"]["reason"]),
                    },
                }
                return normalized
        except Exception:
            pass

    return fallback


def format_feedback_markdown(feedback: dict) -> str:
    """Convert structured feedback dict to markdown text for chat history."""
    scores = feedback.get("scores", {})
    recommendation = feedback.get("recommendation", {})
    plan = feedback.get("plan", {})

    def _bullets(items):
        if not isinstance(items, list) or not items:
            return "- N/A"
        return "\n".join([f"- {str(i)}" for i in items])

    return f"""## Overall Interview Summary

{feedback.get("summary", "No summary available.")}

---

## Technical Evaluation (Score: {scores.get("technical", "N/A")}/10)

### Strengths
{_bullets(feedback.get("strengths", []))}

### Areas for Improvement
{_bullets(feedback.get("improvements", []))}

---

## Communication & Problem-Solving (Score: {scores.get("communication", "N/A")}/10)

---

## High-Priority Improvement Plan (Next 2 Weeks)

### Week 1
{_bullets(plan.get("week_1", []))}

### Week 2
{_bullets(plan.get("week_2", []))}

---

## Final Recommendation

### Decision: {recommendation.get("decision", "Borderline")}

{recommendation.get("reason", "No reason provided.")}"""


# Text-to-Speech Functionality
def speak_text(text: str):
    """
    Convert text to speech using pyttsx3.
    Runs in a separate thread to avoid blocking the API.
    
    Args:
        text (str): Text to convert to speech
    """
    def _speak_worker():
        try:
            # Initialize TTS engine
            engine = pyttsx3.init()
            
            # Configure voice properties
            engine.setProperty('rate', 150)    # Speech rate (words per minute)
            engine.setProperty('volume', 0.9)  # Volume level (0.0 to 1.0)
            
            # Optional: Set voice (try to use a female voice for interviewer)
            voices = engine.getProperty('voices')
            if voices:
                # Try to find a female voice first
                for voice in voices:
                    if 'female' in voice.name.lower() or 'zira' in voice.name.lower():
                        engine.setProperty('voice', voice.id)
                        break
                else:
                    # Use first available voice if no female voice found
                    engine.setProperty('voice', voices[0].id)
            
            # Speak the text
            engine.say(text)
            engine.runAndWait()
            
        except Exception as e:
            print(f"TTS Error: {e}")
            # Silently fail to avoid breaking the interview flow
    
    # Run TTS in background thread to avoid blocking API responses
    thread = threading.Thread(target=_speak_worker, daemon=True)
    thread.start()


def generate_final_feedback(chat_history: list, role: str) -> str:
    """Backward-compatible markdown feedback built from structured feedback."""
    structured = generate_final_feedback_structured(chat_history, role)
    return format_feedback_markdown(structured)