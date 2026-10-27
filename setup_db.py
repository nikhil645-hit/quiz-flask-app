import os
import json
import pymysql
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import random

# Load .env
load_dotenv()

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', 3306))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '1234')
DB_NAME = os.getenv('DB_NAME', 'quiz-app')

def run_setup():
    print(f"Connecting to MySQL server at {DB_HOST}:{DB_PORT} as '{DB_USER}'...")
    
    # Connect without database first to ensure DB exists
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        cursorclass=pymysql.cursors.DictCursor
    )
    
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
            print(f"Database `{DB_NAME}` verified/created.")
            cursor.execute(f"USE `{DB_NAME}`;")
            
            # Read and execute database.sql
            sql_path = os.path.join(os.path.dirname(__file__), 'database.sql')
            with open(sql_path, 'r', encoding='utf-8') as f:
                sql_content = f.read()
            
            # Split and execute non-empty statements
            statements = [s.strip() for s in sql_content.split(';') if s.strip()]
            for stmt in statements:
                cursor.execute(stmt)
            print("Database tables created/verified successfully.")
            
            # 1. Seed Users
            users_to_seed = [
                ('admin', 'admin@quizgen.io', 'admin123', 'admin'),
                ('player1', 'player1@quizgen.io', 'player123', 'user'),
                ('alex_gk', 'alex@quizgen.io', 'alex123', 'user'),
                ('sam_quizmaster', 'sam@quizgen.io', 'sam123', 'user'),
            ]
            
            for username, email, pwd, role in users_to_seed:
                cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
                existing = cursor.fetchone()
                if not existing:
                    pwd_hash = generate_password_hash(pwd)
                    cursor.execute(
                        "INSERT INTO users (username, email, password_hash, role) VALUES (%s, %s, %s, %s)",
                        (username, email, pwd_hash, role)
                    )
                    print(f"  Created user: {username} ({role})")
                else:
                    # Update password hash just in case
                    pwd_hash = generate_password_hash(pwd)
                    cursor.execute(
                        "UPDATE users SET password_hash = %s, role = %s WHERE id = %s",
                        (pwd_hash, role, existing['id'])
                    )
            
            # 2. Seed Questions
            seed_file = os.path.join(os.path.dirname(__file__), 'seed_questions.json')
            if os.path.exists(seed_file):
                with open(seed_file, 'r', encoding='utf-8') as f:
                    questions = json.load(f)
                
                inserted_count = 0
                for q in questions:
                    cursor.execute(
                        "SELECT id FROM questions WHERE question = %s",
                        (q['question'],)
                    )
                    if not cursor.fetchone():
                        cursor.execute(
                            """INSERT INTO questions 
                            (category, difficulty, question, option_a, option_b, option_c, option_d, correct_answer, hint, explanation)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (
                                q['category'],
                                q['difficulty'],
                                q['question'],
                                q['option_a'],
                                q['option_b'],
                                q['option_c'],
                                q['option_d'],
                                q['correct_answer'],
                                q.get('hint', ''),
                                q.get('explanation', '')
                            )
                        )
                        inserted_count += 1
                
                cursor.execute("SELECT COUNT(*) AS cnt FROM questions")
                total_q = cursor.fetchone()['cnt']
                print(f"Questions in database: {total_q} (newly inserted: {inserted_count}).")
            
            # 3. Seed Sample Leaderboard Entries if empty
            cursor.execute("SELECT COUNT(*) AS cnt FROM quiz_attempts")
            attempts_cnt = cursor.fetchone()['cnt']
            if attempts_cnt == 0:
                cursor.execute("SELECT id, username FROM users WHERE role = 'user'")
                db_users = cursor.fetchall()
                sample_attempts = [
                    (db_users[0]['id'], 'alex_gk_token_1', 'Science', 'medium', 10, 1850, 90.0, 120, 2, 9, 'completed'),
                    (db_users[1]['id'], 'sam_token_1', 'History', 'hard', 10, 2100, 100.0, 110, 3, 10, 'completed'),
                    (db_users[0]['id'], 'alex_gk_token_2', 'Technology', 'hard', 10, 1950, 90.0, 140, 2, 7, 'completed'),
                    (db_users[1]['id'], 'sam_token_2', 'Geography', 'medium', 10, 1720, 80.0, 135, 1, 6, 'completed'),
                ]
                for uid, token, cat, diff, tot, sc, acc, tm, hrt, strk, st in sample_attempts:
                    cursor.execute(
                        """INSERT INTO quiz_attempts
                        (user_id, session_token, category, difficulty, total_questions, score, accuracy, time_taken_seconds, hearts_left, max_streak, status, questions_order, completed_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '[]', %s)""",
                        (uid, token, cat, diff, tot, sc, acc, tm, hrt, strk, st, datetime.now() - timedelta(hours=random.randint(1, 48)))
                    )
                print("Seeded sample leaderboard attempts.")

            conn.commit()
            print("Setup and seeding completed successfully!")
    finally:
        conn.close()

if __name__ == '__main__':
    run_setup()
