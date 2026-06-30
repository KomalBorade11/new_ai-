import sys
import os

# Add the backend directory to Python path
backend_path = os.path.join(os.path.dirname(__file__), 'backend')
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from utils import generate_college_questions

# Test the new question generation
test_analysis = {
    "projects": ["E-commerce Website", "Weather App", "Todo List"],
    "skills": ["Java", "SQL", "Python", "HTML", "CSS"]
}

questions = generate_college_questions(test_analysis, None, None)

print("Generated Questions:")
print("=" * 50)
for i, q in enumerate(questions, 1):
    print(f"{i}. {q}")

print(f"\nTotal questions: {len(questions)}")
