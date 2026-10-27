"""
setup_rds.py - Remote Database Provisioning & Seeding Script for Amazon RDS (MySQL)
Connects to Amazon RDS MySQL, creates the database schema, seeds default users,
and loads all 64+ General Knowledge questions with automatic retry logic.
"""

import os
import sys
import time
import json
import pymysql
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

# Load environment configuration
load_dotenv()

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', 3306))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '1234')
DB_NAME = os.getenv('DB_NAME', 'quiz-app')

MAX_RETRIES = 5
RETRY_DELAY = 4

def get_connection_with_retry():
    """Attempt connecting to the RDS/MySQL instance with exponential backoff."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"[Attempt {attempt}/{MAX_RETRIES}] Connecting to MySQL at {DB_HOST}:{DB_PORT}...")
            conn = pymysql.connect(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASSWORD,
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=10,
                autocommit=False
            )
            print("Successfully connected to MySQL database engine!")
            return conn
        except pymysql.err.OperationalError as e:
            code, msg = e.args
            print(f"  Connection error ({code}): {msg}")
            if code == 2003:
                print("  --> TROUBLESHOOTING: Can't connect to MySQL server.")
                print("      1. Verify RDS instance state is 'Available' in AWS Console.")
                print("      2. Check RDS Security Group Inbound Rule: Allow Port 3306 from your EC2 Security Group or IP.")
                print("      3. Verify 'Publicly Accessible' is set to Yes if connecting from outside VPC.")
            elif code == 1045:
                print("  --> TROUBLESHOOTING: Access denied. Check DB_USER and DB_PASSWORD in .env.")
            
            if attempt < MAX_RETRIES:
                print(f"  Waiting {RETRY_DELAY} seconds before retrying...")
                time.sleep(RETRY_DELAY)
            else:
                print("\nFATAL: Maximum connection retries reached. Aborting setup.")
                raise e

def run_rds_setup():
    print("=" * 65)
    print("      AMAZON RDS (MySQL) PROVISIONING & SEEDING SCRIPT")
    print("=" * 65)
    print(f"Target Host     : {DB_HOST}")
    print(f"Target Port     : {DB_PORT}")
    print(f"Database Name   : {DB_NAME}")
    print(f"Database User   : {DB_USER}")
    print("=" * 65)

    conn = get_connection_with_retry()
    try:
        with conn.cursor() as cursor:
            # 1. Create database if it does not exist
            print(f"\n1. Ensuring database `{DB_NAME}` exists...")
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
            cursor.execute(f"USE `{DB_NAME}`;")
            print(f"   Database `{DB_NAME}` selected.")

            # 2. Execute schema from database.sql
            sql_file = os.path.join(os.path.dirname(__file__), 'database.sql')
            print(f"\n2. Executing schema definitions from {os.path.basename(sql_file)}...")
            with open(sql_file, 'r', encoding='utf-8') as f:
                sql_content = f.read()

            statements = [s.strip() for s in sql_content.split(';') if s.strip()]
            for stmt in statements:
                cursor.execute(stmt)
            print(f"   Executed {len(statements)} DDL schema statements successfully.")

            # 3. Seed Users
            print("\n3. Seeding Administrator and Demo Accounts...")
            users_to_seed = [
                ('admin', 'admin@quizgen.io', 'admin123', 'admin'),
                ('player1', 'player1@quizgen.io', 'player123', 'user'),
                ('alex_gk', 'alex@quizgen.io', 'alex123', 'user'),
                ('sam_quizmaster', 'sam@quizgen.io', 'sam123', 'user'),
            ]
            for username, email, pwd, role in users_to_seed:
                cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
                existing = cursor.fetchone()
                pwd_hash = generate_password_hash(pwd)
                if not existing:
                    cursor.execute(
                        "INSERT INTO users (username, email, password_hash, role) VALUES (%s, %s, %s, %s)",
                        (username, email, pwd_hash, role)
                    )
                    print(f"   + Created user: {username} ({role})")
                else:
                    cursor.execute(
                        "UPDATE users SET password_hash = %s, role = %s WHERE id = %s",
                        (pwd_hash, role, existing['id'])
                    )
                    print(f"   ~ Verified user: {username} ({role})")

            # 4. Seed Questions from seed_questions.json
            seed_file = os.path.join(os.path.dirname(__file__), 'seed_questions.json')
            print(f"\n4. Loading General Knowledge Questions from {os.path.basename(seed_file)}...")
            with open(seed_file, 'r', encoding='utf-8') as f:
                questions = json.load(f)

            inserted = 0
            for q in questions:
                cursor.execute("SELECT id FROM questions WHERE question = %s", (q['question'],))
                if not cursor.fetchone():
                    cursor.execute(
                        """INSERT INTO questions
                        (category, difficulty, question, option_a, option_b, option_c, option_d, correct_answer, hint, explanation)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            q['category'], q['difficulty'], q['question'],
                            q['option_a'], q['option_b'], q['option_c'], q['option_d'],
                            q['correct_answer'], q.get('hint', ''), q.get('explanation', '')
                        )
                    )
                    inserted += 1

            cursor.execute("SELECT COUNT(*) AS cnt FROM questions")
            total_questions = cursor.fetchone()['cnt']
            print(f"   Total Questions in Database: {total_questions} ({inserted} newly inserted).")

            # 5. Commit all changes
            conn.commit()
            print("\n" + "=" * 65)
            print("   RDS DATABASE SETUP & SEEDING COMPLETED SUCCESSFULLY!")
            print("=" * 65)

    except Exception as e:
        conn.rollback()
        print(f"\nERROR during RDS provisioning: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()

if __name__ == '__main__':
    run_rds_setup()
