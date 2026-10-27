import os
import csv
import io
import json
import random
import uuid
from datetime import datetime
from functools import wraps

import pymysql
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# AWS Integration & Fallback Module
from aws_services import (
    CLOUDWATCH_LOG_GROUP,
    LOCAL_UPLOADS_DIR,
    S3_BUCKET_NAME,
    SNS_TOPIC_ARN,
    USE_AWS,
    generate_presigned_url,
    get_aws_connectivity_status,
    publish_quiz_result_sns,
    save_file_s3_or_local,
    setup_cloudwatch_logging,
    subscribe_email_sns,
)

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'quiz-generator-secret-key-super-secure-2026')

# Database configuration from environment variables (Amazon RDS / Local MySQL)
app.config['DB_HOST'] = os.getenv('DB_HOST', 'localhost')
app.config['DB_PORT'] = int(os.getenv('DB_PORT', 3306))
app.config['DB_USER'] = os.getenv('DB_USER', 'root')
app.config['DB_PASSWORD'] = os.getenv('DB_PASSWORD', '1234')
app.config['DB_NAME'] = os.getenv('DB_NAME', 'quiz-app')

# Attach CloudWatch Logs or Console Stream Logger
setup_cloudwatch_logging(app)

def get_db():
    """Create and return a new MySQL/RDS connection with DictCursor."""
    return pymysql.connect(
        host=app.config['DB_HOST'],
        port=app.config['DB_PORT'],
        user=app.config['DB_USER'],
        password=app.config['DB_PASSWORD'],
        database=app.config['DB_NAME'],
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False
    )

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            return jsonify({'error': 'Admin authorization required'}), 403
        return f(*args, **kwargs)
    return decorated_function

# -------------------------------------------------------------
# System & Health Check Endpoints
# -------------------------------------------------------------
@app.route('/health')
def health():
    """Health check endpoint for AWS ALB / monitoring."""
    db_status = "connected"
    try:
        conn = get_db()
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 AS ok")
            cursor.fetchone()
        conn.close()
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
        app.logger.error("[APP_ERROR] Health check failed: %s", e)
        return jsonify({
            'status': 'degraded',
            'database': db_status,
            'aws_mode': 'AWS Cloud' if USE_AWS else 'Local Fallback',
            'timestamp': datetime.utcnow().isoformat()
        }), 500

    return jsonify({
        'status': 'ok',
        'database': db_status,
        'aws_mode': 'AWS Cloud' if USE_AWS else 'Local Fallback',
        'timestamp': datetime.utcnow().isoformat()
    }), 200

# -------------------------------------------------------------
# AWS Status Page & API
# -------------------------------------------------------------
@app.route('/aws-status')
def aws_status_page():
    """Render the AWS Architecture live status dashboard."""
    return render_template('aws_status.html')

@app.route('/api/aws/status')
def api_aws_status():
    """API endpoint providing live connectivity status for RDS, S3, SNS, and CloudWatch."""
    return jsonify(get_aws_connectivity_status(get_db))

# -------------------------------------------------------------
# Local Fallback File Downloads Route
# -------------------------------------------------------------
@app.route('/downloads/<path:filename>')
def serve_download(filename):
    """Serve files uploaded to local storage in fallback mode."""
    return send_from_directory(LOCAL_UPLOADS_DIR, filename)

# -------------------------------------------------------------
# Authentication Endpoints
# -------------------------------------------------------------
@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not username or not email or not password:
        return jsonify({'error': 'Username, email, and password are required'}), 400

    if len(username) < 3:
        return jsonify({'error': 'Username must be at least 3 characters'}), 400

    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE username = %s OR email = %s", (username, email))
            if cursor.fetchone():
                return jsonify({'error': 'Username or email already exists'}), 409

            pwd_hash = generate_password_hash(password)
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, role) VALUES (%s, %s, %s, %s)",
                (username, email, pwd_hash, 'user')
            )
            user_id = cursor.lastrowid
            conn.commit()

            # Set session
            session['user_id'] = user_id
            session['username'] = username
            session['role'] = 'user'

            app.logger.info("[AUTH_REGISTER] User registered: %s (id: %s)", username, user_id)

            return jsonify({
                'message': 'Registration successful',
                'user': {'id': user_id, 'username': username, 'role': 'user', 'email': email}
            }), 201
    except Exception as e:
        conn.rollback()
        app.logger.error("[APP_ERROR] Registration error: %s", e)
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    identifier = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not identifier or not password:
        return jsonify({'error': 'Username/email and password required'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, email, password_hash, role FROM users WHERE username = %s OR email = %s",
                (identifier, identifier.lower())
            )
            user = cursor.fetchone()
            if not user or not check_password_hash(user['password_hash'], password):
                app.logger.warning("[AUTH_LOGIN_FAIL] Failed login attempt for identifier: %s", identifier)
                return jsonify({'error': 'Invalid username/email or password'}), 401

            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']

            app.logger.info("[AUTH_LOGIN] Successful login: %s (Role: %s)", user['username'], user['role'])

            return jsonify({
                'message': 'Login successful',
                'user': {
                    'id': user['id'],
                    'username': user['username'],
                    'email': user['email'],
                    'role': user['role']
                }
            }), 200
    finally:
        conn.close()

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    uname = session.get('username', 'Guest')
    app.logger.info("[AUTH_LOGOUT] User logged out: %s", uname)
    session.clear()
    return jsonify({'message': 'Logged out successfully'}), 200

@app.route('/api/auth/me', methods=['GET'])
def current_user():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'authenticated': False, 'user': None}), 200

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, username, email, role, sns_subscribed FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if not user:
                session.clear()
                return jsonify({'authenticated': False, 'user': None}), 200

            return jsonify({'authenticated': True, 'user': user}), 200
    finally:
        conn.close()

# -------------------------------------------------------------
# Amazon SNS Email Subscription Endpoint
# -------------------------------------------------------------
@app.route('/api/user/subscribe-sns', methods=['POST'])
def subscribe_sns():
    """Subscribe user to the SNS topic for score notifications."""
    data = request.get_json() or {}
    email = data.get('email')

    user_id = session.get('user_id')
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            if user_id and not email:
                cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
                row = cursor.fetchone()
                if row:
                    email = row['email']

            if not email:
                return jsonify({'error': 'Email address required to subscribe'}), 400

            success, message = subscribe_email_sns(email)
            if success and user_id:
                cursor.execute("UPDATE users SET sns_subscribed = 1 WHERE id = %s", (user_id,))
                conn.commit()

            return jsonify({'success': success, 'message': message}), (200 if success else 500)
    finally:
        conn.close()

# -------------------------------------------------------------
# Categories & Generator Configuration
# -------------------------------------------------------------
@app.route('/api/categories', methods=['GET'])
def get_categories():
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT category, COUNT(*) as count FROM questions GROUP BY category ORDER BY category ASC"
            )
            categories = cursor.fetchall()
            return jsonify({'categories': categories}), 200
    finally:
        conn.close()

# -------------------------------------------------------------
# Quiz Game Engine APIs
# -------------------------------------------------------------
@app.route('/api/quiz/start', methods=['POST'])
def start_quiz():
    """Start a new customized quiz session."""
    data = request.get_json() or {}
    category = data.get('category', 'All')
    difficulty = data.get('difficulty', 'all').lower()
    num_questions = int(data.get('num_questions', 10))

    if num_questions not in [5, 10, 15, 20]:
        num_questions = 10

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            query = "SELECT id FROM questions WHERE 1=1"
            params = []

            if category != 'All':
                query += " AND category = %s"
                params.append(category)

            if difficulty != 'all':
                query += " AND difficulty = %s"
                params.append(difficulty)

            cursor.execute(query, tuple(params))
            all_ids = [row['id'] for row in cursor.fetchall()]

            # Fallback if filtered count is less than requested
            if len(all_ids) < num_questions:
                cursor.execute("SELECT id FROM questions")
                all_ids = [row['id'] for row in cursor.fetchall()]

            selected_ids = random.sample(all_ids, min(num_questions, len(all_ids)))
            session_token = str(uuid.uuid4())
            user_id = session.get('user_id')
            username = session.get('username', 'Guest')

            cursor.execute(
                """INSERT INTO quiz_attempts
                (user_id, session_token, category, difficulty, total_questions, current_question_index,
                 score, streak, max_streak, hearts_left, hints_5050_left, hints_text_left, skips_left,
                 status, time_taken_seconds, accuracy, questions_order)
                VALUES (%s, %s, %s, %s, %s, 0, 0, 0, 0, 3, 1, 1, 1, 'in_progress', 0, 0.0, %s)""",
                (user_id, session_token, category, difficulty, len(selected_ids), json.dumps(selected_ids))
            )
            attempt_id = cursor.lastrowid
            conn.commit()

            app.logger.info(
                "[QUIZ_START] Attempt #%s started by %s | Category: %s | Difficulty: %s | Questions: %s",
                attempt_id, username, category, difficulty, len(selected_ids)
            )

            return jsonify({
                'attempt_id': attempt_id,
                'session_token': session_token,
                'total_questions': len(selected_ids),
                'category': category,
                'difficulty': difficulty,
                'hearts_left': 3,
                'hints_5050_left': 1,
                'hints_text_left': 1,
                'skips_left': 1
            }), 201
    except Exception as e:
        conn.rollback()
        app.logger.error("[APP_ERROR] Error starting quiz: %s", e)
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/quiz/<int:attempt_id>/current', methods=['GET'])
def get_current_question(attempt_id):
    """Retrieve the current question for the attempt without revealing answers."""
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM quiz_attempts WHERE id = %s", (attempt_id,))
            attempt = cursor.fetchone()
            if not attempt:
                return jsonify({'error': 'Quiz attempt not found'}), 404

            if attempt['status'] != 'in_progress':
                return jsonify({
                    'status': attempt['status'],
                    'message': 'Quiz is already completed or ended',
                    'is_finished': True
                }), 200

            q_ids = json.loads(attempt['questions_order'])
            curr_idx = attempt['current_question_index']

            if curr_idx >= len(q_ids):
                # Mark as completed and process artifacts
                process_quiz_completion(attempt_id)
                return jsonify({'status': 'completed', 'is_finished': True}), 200

            current_q_id = q_ids[curr_idx]
            cursor.execute(
                "SELECT id, category, difficulty, question, option_a, option_b, option_c, option_d, image_s3_key FROM questions WHERE id = %s",
                (current_q_id,)
            )
            q = cursor.fetchone()

            options = [q['option_a'], q['option_b'], q['option_c'], q['option_d']]
            random.seed(attempt['id'] * 100 + curr_idx)
            random.shuffle(options)
            random.seed()

            image_url = None
            if q.get('image_s3_key'):
                image_url = generate_presigned_url(q['image_s3_key'], expires_in=900)

            return jsonify({
                'attempt_id': attempt['id'],
                'question_index': curr_idx,
                'total_questions': attempt['total_questions'],
                'question_id': q['id'],
                'category': q['category'],
                'difficulty': q['difficulty'],
                'question': q['question'],
                'options': options,
                'image_url': image_url,
                'hearts_left': attempt['hearts_left'],
                'hints_5050_left': attempt['hints_5050_left'],
                'hints_text_left': attempt['hints_text_left'],
                'skips_left': attempt['skips_left'],
                'score': attempt['score'],
                'streak': attempt['streak'],
                'status': attempt['status'],
                'time_limit': 30
            }), 200
    finally:
        conn.close()

@app.route('/api/quiz/<int:attempt_id>/hint', methods=['POST'])
def use_hint(attempt_id):
    """Use a 50-50 or Text hint. Validates hint limits and returns clue."""
    data = request.get_json() or {}
    hint_type = data.get('hint_type')

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM quiz_attempts WHERE id = %s", (attempt_id,))
            attempt = cursor.fetchone()
            if not attempt or attempt['status'] != 'in_progress':
                return jsonify({'error': 'Active quiz attempt required'}), 400

            q_ids = json.loads(attempt['questions_order'])
            curr_q_id = q_ids[attempt['current_question_index']]
            cursor.execute("SELECT * FROM questions WHERE id = %s", (curr_q_id,))
            q = cursor.fetchone()

            if hint_type == '50-50':
                if attempt['hints_5050_left'] <= 0:
                    return jsonify({'error': 'No 50-50 hints remaining'}), 400

                all_options = [q['option_a'], q['option_b'], q['option_c'], q['option_d']]
                wrong_options = [opt for opt in all_options if opt != q['correct_answer']]
                disabled_options = random.sample(wrong_options, 2)

                cursor.execute(
                    "UPDATE quiz_attempts SET hints_5050_left = hints_5050_left - 1 WHERE id = %s",
                    (attempt_id,)
                )
                conn.commit()

                return jsonify({
                    'hint_type': '50-50',
                    'disabled_options': disabled_options,
                    'hints_5050_left': attempt['hints_5050_left'] - 1
                }), 200

            elif hint_type == 'text':
                if attempt['hints_text_left'] <= 0:
                    return jsonify({'error': 'No text hints remaining'}), 400

                cursor.execute(
                    "UPDATE quiz_attempts SET hints_text_left = hints_text_left - 1 WHERE id = %s",
                    (attempt_id,)
                )
                conn.commit()

                return jsonify({
                    'hint_type': 'text',
                    'hint_text': q['hint'],
                    'hints_text_left': attempt['hints_text_left'] - 1
                }), 200
            else:
                return jsonify({'error': 'Invalid hint type'}), 400
    finally:
        conn.close()

@app.route('/api/quiz/<int:attempt_id>/skip', methods=['POST'])
def skip_question(attempt_id):
    """Skip the current question (1 allowed per quiz)."""
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM quiz_attempts WHERE id = %s", (attempt_id,))
            attempt = cursor.fetchone()
            if not attempt or attempt['status'] != 'in_progress':
                return jsonify({'error': 'Active quiz attempt required'}), 400

            if attempt['skips_left'] <= 0:
                return jsonify({'error': 'No skips remaining'}), 400

            q_ids = json.loads(attempt['questions_order'])
            curr_idx = attempt['current_question_index']
            curr_q_id = q_ids[curr_idx]

            cursor.execute(
                """INSERT INTO attempt_answers
                (attempt_id, question_id, user_answer, is_correct, points_awarded, time_taken_seconds, hint_used, is_skipped)
                VALUES (%s, %s, %s, 0, 0, 0, 'none', 1)""",
                (attempt_id, curr_q_id, 'SKIPPED')
            )

            new_idx = curr_idx + 1
            new_status = 'completed' if new_idx >= len(q_ids) else 'in_progress'

            cursor.execute(
                """UPDATE quiz_attempts
                SET current_question_index = %s, skips_left = skips_left - 1, status = %s
                WHERE id = %s""",
                (new_idx, new_status, attempt_id)
            )
            conn.commit()

            if new_status == 'completed':
                process_quiz_completion(attempt_id)

            return jsonify({
                'skipped': True,
                'skips_left': attempt['skips_left'] - 1,
                'is_finished': new_status != 'in_progress',
                'status': new_status
            }), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/quiz/<int:attempt_id>/answer', methods=['POST'])
def submit_answer(attempt_id):
    """
    Submit answer for the current question.
    Calculates score, streak, time bonus, updates lives/hearts.
    Returns instant feedback with explanation.
    """
    data = request.get_json() or {}
    selected_answer = data.get('selected_answer')
    time_spent = min(30, max(0, int(data.get('time_spent', 0))))
    timed_out = bool(data.get('timed_out', False))
    hint_used = data.get('hint_used', 'none')

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM quiz_attempts WHERE id = %s", (attempt_id,))
            attempt = cursor.fetchone()
            if not attempt:
                return jsonify({'error': 'Quiz attempt not found'}), 404

            if attempt['status'] != 'in_progress':
                return jsonify({'error': 'Quiz has already finished', 'status': attempt['status']}), 400

            q_ids = json.loads(attempt['questions_order'])
            curr_idx = attempt['current_question_index']

            if curr_idx >= len(q_ids):
                return jsonify({'error': 'All questions answered', 'status': 'completed'}), 400

            curr_q_id = q_ids[curr_idx]
            cursor.execute("SELECT * FROM questions WHERE id = %s", (curr_q_id,))
            question = cursor.fetchone()

            is_correct = False
            points_awarded = 0
            new_streak = 0
            new_hearts = attempt['hearts_left']

            if not timed_out and selected_answer == question['correct_answer']:
                is_correct = True
                new_streak = attempt['streak'] + 1

                diff_points = {'easy': 100, 'medium': 200, 'hard': 300}
                base = diff_points.get(question['difficulty'].lower(), 150)

                if '50-50' in hint_used:
                    base = int(base * 0.5)
                elif 'text' in hint_used:
                    base = int(base * 0.75)

                streak_bonus = (new_streak - 1) * 25
                time_bonus = max(0, 30 - time_spent) * 5

                points_awarded = base + streak_bonus + time_bonus
            else:
                new_hearts = max(0, attempt['hearts_left'] - 1)
                new_streak = 0

            # Record answer in attempt_answers
            cursor.execute(
                """INSERT INTO attempt_answers
                (attempt_id, question_id, user_answer, is_correct, points_awarded, time_taken_seconds, hint_used, is_skipped)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 0)""",
                (attempt_id, curr_q_id, selected_answer if not timed_out else 'TIMEOUT', 1 if is_correct else 0, points_awarded, time_spent, hint_used)
            )

            new_score = attempt['score'] + points_awarded
            new_max_streak = max(attempt['max_streak'], new_streak)
            new_time_taken = attempt['time_taken_seconds'] + time_spent
            new_idx = curr_idx + 1

            new_status = 'in_progress'
            if new_hearts <= 0:
                new_status = 'game_over'
            elif new_idx >= len(q_ids):
                new_status = 'completed'

            cursor.execute(
                "SELECT COUNT(*) AS total_ans, SUM(is_correct) AS correct_ans FROM attempt_answers WHERE attempt_id = %s",
                (attempt_id,)
            )
            stats = cursor.fetchone()
            tot = stats['total_ans'] or 1
            corr = stats['correct_ans'] or 0
            accuracy = round((corr / tot) * 100, 1)

            cursor.execute(
                """UPDATE quiz_attempts
                SET current_question_index = %s, score = %s, streak = %s, max_streak = %s,
                    hearts_left = %s, status = %s, time_taken_seconds = %s, accuracy = %s
                WHERE id = %s""",
                (new_idx, new_score, new_streak, new_max_streak, new_hearts, new_status, new_time_taken, accuracy, attempt_id)
            )
            conn.commit()

            # If quiz ended, trigger completion pipeline (S3, SNS, CloudWatch)
            if new_status in ('game_over', 'completed'):
                process_quiz_completion(attempt_id)

            return jsonify({
                'is_correct': is_correct,
                'timed_out': timed_out,
                'correct_answer': question['correct_answer'],
                'explanation': question['explanation'],
                'points_awarded': points_awarded,
                'streak': new_streak,
                'hearts_left': new_hearts,
                'current_score': new_score,
                'is_game_over': new_status == 'game_over',
                'is_completed': new_status == 'completed',
                'status': new_status,
                'accuracy': accuracy
            }), 200
    except Exception as e:
        conn.rollback()
        app.logger.error("[APP_ERROR] Error in submit_answer: %s", e)
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

def generate_pdf_report_bytes(attempt, answers):
    """Generate a clean binary PDF using fpdf2 with fallback to HTML template."""
    try:
        from fpdf import FPDF
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # Header Banner
        pdf.set_fill_color(30, 41, 59)
        pdf.rect(0, 0, 210, 30, 'F')
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('helvetica', 'B', 15)
        pdf.set_y(8)
        pdf.cell(0, 8, "ONLINE GK QUIZ GENERATOR - RESULT REPORT", align='C', new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('helvetica', 'I', 9)
        pdf.set_text_color(203, 213, 225)
        pdf.cell(0, 6, "Official Certificate & Performance Breakdown", align='C', new_x='LMARGIN', new_y='NEXT')

        pdf.set_y(36)
        pdf.set_text_color(15, 23, 42)

        meta = [
            ("Candidate:", str(attempt.get('username') or 'Guest'), "Attempt ID:", f"#{attempt.get('id')}"),
            ("Category:", str(attempt.get('category') or 'All GK'), "Difficulty:", str(attempt.get('difficulty')).capitalize()),
            ("Score:", str(attempt.get('score', 0)), "Accuracy:", f"{attempt.get('accuracy', 0)}%"),
            ("Time Taken:", f"{attempt.get('time_taken_seconds', 0)}s", "Status:", str(attempt.get('status')).upper())
        ]

        for row in meta:
            pdf.set_font('helvetica', 'B', 9)
            pdf.set_fill_color(241, 245, 249)
            pdf.cell(35, 7, row[0], border=1, fill=True)
            pdf.set_font('helvetica', '', 9)
            pdf.cell(60, 7, row[1][:30], border=1)
            pdf.set_font('helvetica', 'B', 9)
            pdf.cell(35, 7, row[2], border=1, fill=True)
            pdf.set_font('helvetica', '', 9)
            pdf.cell(60, 7, row[3][:30], border=1, new_x='LMARGIN', new_y='NEXT')

        pdf.ln(5)
        pdf.set_font('helvetica', 'B', 11)
        pdf.cell(0, 7, "Question-by-Question Review", new_x='LMARGIN', new_y='NEXT')

        pdf.set_font('helvetica', 'B', 8)
        pdf.set_fill_color(226, 232, 240)
        pdf.cell(8, 6, "#", border=1, fill=True, align='C')
        pdf.cell(92, 6, "Question", border=1, fill=True)
        pdf.cell(42, 6, "Your Answer", border=1, fill=True)
        pdf.cell(35, 6, "Correct Answer", border=1, fill=True)
        pdf.cell(13, 6, "Result", border=1, fill=True, align='C', new_x='LMARGIN', new_y='NEXT')

        pdf.set_font('helvetica', '', 8)
        for idx, ans in enumerate(answers, 1):
            q_clean = (ans.get('question') or '').encode('latin-1', 'replace').decode('latin-1')[:55]
            u_clean = (ans.get('user_answer') or 'No Answer').encode('latin-1', 'replace').decode('latin-1')[:24]
            c_clean = (ans.get('correct_answer') or '').encode('latin-1', 'replace').decode('latin-1')[:20]
            is_corr = bool(ans.get('is_correct'))

            pdf.cell(8, 6, str(idx), border=1, align='C')
            pdf.cell(92, 6, q_clean, border=1)
            pdf.cell(42, 6, u_clean, border=1)
            pdf.cell(35, 6, c_clean, border=1)

            if is_corr:
                pdf.set_text_color(22, 101, 52)
            else:
                pdf.set_text_color(185, 28, 28)
            pdf.cell(13, 6, "PASS" if is_corr else "FAIL", border=1, align='C', new_x='LMARGIN', new_y='NEXT')
            pdf.set_text_color(15, 23, 42)

        return bytes(pdf.output()), "application/pdf", ".pdf"
    except Exception as e:
        app.logger.warning("fpdf2 PDF generation fallback to HTML: %s", e)
        html_content = render_template('pdf_report.html', attempt=attempt, answers=answers)
        return html_content.encode('utf-8'), "text/html", ".html"

# -------------------------------------------------------------
# Amazon S3 & SNS Completion Pipeline Helper
# -------------------------------------------------------------
def process_quiz_completion(attempt_id):
    """
    Called when a quiz finishes (completed or game_over):
    1. Generates result CSV and PDF (or HTML report fallback).
    2. Uploads them to S3 (results/<user_id>/) or local fallback.
    3. Saves S3 keys in quiz_attempts table.
    4. Calculates user's leaderboard rank.
    5. Publishes result notification to Amazon SNS.
    6. Logs event to Amazon CloudWatch.
    """
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT qa.*, COALESCE(u.username, 'Guest') as username, u.email
                FROM quiz_attempts qa
                LEFT JOIN users u ON qa.user_id = u.id
                WHERE qa.id = %s""",
                (attempt_id,)
            )
            attempt = cursor.fetchone()
            if not attempt:
                return

            cursor.execute(
                """SELECT aa.*, q.question, q.correct_answer, q.explanation, q.category, q.difficulty
                FROM attempt_answers aa
                JOIN questions q ON aa.question_id = q.id
                WHERE aa.attempt_id = %s
                ORDER BY aa.id ASC""",
                (attempt_id,)
            )
            answers = cursor.fetchall()

            # Determine rank on leaderboard
            cursor.execute(
                """SELECT COUNT(*) + 1 AS rank_position
                FROM quiz_attempts
                WHERE status = 'completed' AND score > %s""",
                (attempt['score'],)
            )
            rank_data = cursor.fetchone()
            rank = rank_data['rank_position'] if rank_data else 1

            # 1. Generate CSV bytes
            csv_output = io.StringIO()
            writer = csv.writer(csv_output)
            writer.writerow(["QUIZ RESULT SUMMARY (AWS S3 ARCHIVED)"])
            writer.writerow(["Attempt ID", attempt['id']])
            writer.writerow(["Player", attempt['username']])
            writer.writerow(["Category", attempt['category']])
            writer.writerow(["Difficulty", attempt['difficulty']])
            writer.writerow(["Score", attempt['score']])
            writer.writerow(["Accuracy", f"{attempt['accuracy']}%"])
            writer.writerow(["Time Taken (s)", attempt['time_taken_seconds']])
            writer.writerow(["Status", attempt['status']])
            writer.writerow([])
            writer.writerow(["#", "Question", "Category", "Your Answer", "Correct Answer", "Result", "Points"])
            for idx, ans in enumerate(answers, 1):
                writer.writerow([
                    idx, ans['question'], ans['category'],
                    ans['user_answer'], ans['correct_answer'],
                    "CORRECT" if ans['is_correct'] else "INCORRECT",
                    ans['points_awarded']
                ])
            csv_bytes = csv_output.getvalue().encode('utf-8')

            # 2. Generate PDF bytes (fpdf2 or fallback)
            pdf_bytes, pdf_mimetype, pdf_ext = generate_pdf_report_bytes(attempt, answers)

            # 3. Upload to S3 under results/<user_id>/
            user_folder = str(attempt['user_id'] or 'guest')
            csv_key = f"results/{user_folder}/attempt_{attempt_id}.csv"
            pdf_key = f"results/{user_folder}/attempt_{attempt_id}{pdf_ext}"

            saved_csv_key, csv_url = save_file_s3_or_local(csv_bytes, csv_key, "text/csv")
            saved_pdf_key, pdf_url = save_file_s3_or_local(pdf_bytes, pdf_key, pdf_mimetype)

            # Update DB with S3 keys and completion timestamp
            cursor.execute(
                """UPDATE quiz_attempts
                SET pdf_s3_key = %s, csv_s3_key = %s, completed_at = NOW()
                WHERE id = %s""",
                (saved_pdf_key, saved_csv_key, attempt_id)
            )
            conn.commit()

            # 4. Publish to Amazon SNS
            publish_quiz_result_sns(
                username=attempt['username'],
                category=attempt['category'],
                difficulty=attempt['difficulty'],
                score=attempt['score'],
                accuracy=attempt['accuracy'],
                rank=rank
            )

            # 5. CloudWatch Logging
            app.logger.info(
                "[QUIZ_FINISH] Attempt #%s finished by %s | Score: %s | Accuracy: %s%% | Status: %s | S3 Keys: [%s, %s]",
                attempt_id, attempt['username'], attempt['score'], attempt['accuracy'], attempt['status'], saved_pdf_key, saved_csv_key
            )
    except Exception as e:
        conn.rollback()
        app.logger.error("[APP_ERROR] Error during quiz completion processing: %s", e)
    finally:
        conn.close()

@app.route('/api/quiz/<int:attempt_id>/result', methods=['GET'])
def get_quiz_result(attempt_id):
    """Return complete quiz results, statistics, full question review, and S3 pre-signed URLs."""
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT qa.*, u.username
                FROM quiz_attempts qa
                LEFT JOIN users u ON qa.user_id = u.id
                WHERE qa.id = %s""",
                (attempt_id,)
            )
            attempt = cursor.fetchone()
            if not attempt:
                return jsonify({'error': 'Attempt not found'}), 404

            cursor.execute(
                """SELECT aa.*, q.question, q.option_a, q.option_b, q.option_c, q.option_d,
                          q.correct_answer, q.explanation, q.category, q.difficulty, q.image_s3_key
                FROM attempt_answers aa
                JOIN questions q ON aa.question_id = q.id
                WHERE aa.attempt_id = %s
                ORDER BY aa.id ASC""",
                (attempt_id,)
            )
            reviews = cursor.fetchall()

            # Pre-signed URLs for PDF and CSV (15-min expiry / 900s)
            pdf_url = generate_presigned_url(attempt['pdf_s3_key'], expires_in=900) if attempt.get('pdf_s3_key') else f"/api/attempts/{attempt_id}/export/pdf"
            csv_url = generate_presigned_url(attempt['csv_s3_key'], expires_in=900) if attempt.get('csv_s3_key') else f"/api/attempts/{attempt_id}/export/csv"

            hints_used = (1 - attempt['hints_5050_left']) + (1 - attempt['hints_text_left'])

            return jsonify({
                'attempt': {
                    'id': attempt['id'],
                    'category': attempt['category'],
                    'difficulty': attempt['difficulty'],
                    'total_questions': attempt['total_questions'],
                    'answered_questions': len(reviews),
                    'score': attempt['score'],
                    'accuracy': attempt['accuracy'],
                    'time_taken_seconds': attempt['time_taken_seconds'],
                    'hearts_left': attempt['hearts_left'],
                    'max_streak': attempt['max_streak'],
                    'hints_used': hints_used,
                    'status': attempt['status'],
                    'username': attempt['username'] or 'Guest',
                    'created_at': attempt['created_at'].strftime('%Y-%m-%d %H:%M') if attempt['created_at'] else '',
                    'pdf_url': pdf_url,
                    'csv_url': csv_url,
                    'pdf_s3_key': attempt.get('pdf_s3_key'),
                    'csv_s3_key': attempt.get('csv_s3_key')
                },
                'reviews': reviews
            }), 200
    finally:
        conn.close()

# -------------------------------------------------------------
# Leaderboard & User History
# -------------------------------------------------------------
@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    category = request.args.get('category', 'All')
    limit = int(request.args.get('limit', 10))

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            query = """
                SELECT qa.id, qa.score, qa.accuracy, qa.time_taken_seconds, qa.category, qa.difficulty,
                       qa.completed_at, COALESCE(u.username, 'Guest') as username
                FROM quiz_attempts qa
                LEFT JOIN users u ON qa.user_id = u.id
                WHERE qa.status = 'completed'
            """
            params = []
            if category != 'All':
                query += " AND qa.category = %s"
                params.append(category)

            query += " ORDER BY qa.score DESC, qa.accuracy DESC, qa.time_taken_seconds ASC LIMIT %s"
            params.append(limit)

            cursor.execute(query, tuple(params))
            leaders = cursor.fetchall()

            for i, leader in enumerate(leaders, 1):
                leader['rank'] = i
                if leader['completed_at']:
                    leader['date'] = leader['completed_at'].strftime('%b %d, %Y')
                else:
                    leader['date'] = 'Recent'

            return jsonify({'leaderboard': leaders}), 200
    finally:
        conn.close()

@app.route('/api/user/history', methods=['GET'])
def get_user_history():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Authentication required'}), 401

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT id, category, difficulty, total_questions, score, accuracy,
                          time_taken_seconds, hearts_left, status, created_at, pdf_s3_key, csv_s3_key
                FROM quiz_attempts
                WHERE user_id = %s
                ORDER BY created_at DESC LIMIT 50""",
                (user_id,)
            )
            history = cursor.fetchall()
            for h in history:
                if h['created_at']:
                    h['date'] = h['created_at'].strftime('%Y-%m-%d %H:%M')
                h['pdf_url'] = generate_presigned_url(h['pdf_s3_key'], expires_in=900) if h.get('pdf_s3_key') else f"/api/attempts/{h['id']}/export/pdf"
                h['csv_url'] = generate_presigned_url(h['csv_s3_key'], expires_in=900) if h.get('csv_s3_key') else f"/api/attempts/{h['id']}/export/csv"

            cursor.execute(
                """SELECT COUNT(*) as total_attempts,
                          COALESCE(MAX(score), 0) as high_score,
                          COALESCE(AVG(accuracy), 0) as avg_accuracy
                FROM quiz_attempts
                WHERE user_id = %s AND status = 'completed'""",
                (user_id,)
            )
            stats = cursor.fetchone()
            stats['avg_accuracy'] = round(stats['avg_accuracy'], 1)

            return jsonify({'history': history, 'stats': stats}), 200
    finally:
        conn.close()

# -------------------------------------------------------------
# Direct CSV and PDF Export Fallbacks
# -------------------------------------------------------------
@app.route('/api/attempts/<int:attempt_id>/export/csv', methods=['GET'])
def export_attempt_csv(attempt_id):
    """Generate and return CSV attachment."""
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT qa.*, COALESCE(u.username, 'Guest') as username
                FROM quiz_attempts qa
                LEFT JOIN users u ON qa.user_id = u.id
                WHERE qa.id = %s""",
                (attempt_id,)
            )
            attempt = cursor.fetchone()
            if not attempt:
                return jsonify({'error': 'Attempt not found'}), 404

            cursor.execute(
                """SELECT aa.*, q.question, q.correct_answer, q.category, q.difficulty
                FROM attempt_answers aa
                JOIN questions q ON aa.question_id = q.id
                WHERE aa.attempt_id = %s
                ORDER BY aa.id ASC""",
                (attempt_id,)
            )
            answers = cursor.fetchall()

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["QUIZ RESULT SUMMARY"])
            writer.writerow(["Attempt ID", attempt['id']])
            writer.writerow(["Player", attempt['username']])
            writer.writerow(["Category", attempt['category']])
            writer.writerow(["Difficulty", attempt['difficulty']])
            writer.writerow(["Score", attempt['score']])
            writer.writerow(["Accuracy", f"{attempt['accuracy']}%"])
            writer.writerow(["Time Taken (s)", attempt['time_taken_seconds']])
            writer.writerow(["Hearts Left", attempt['hearts_left']])
            writer.writerow(["Status", attempt['status']])
            writer.writerow([])
            writer.writerow(["#", "Question", "Category", "Difficulty", "Your Answer", "Correct Answer", "Result", "Points Awarded"])
            for idx, ans in enumerate(answers, 1):
                writer.writerow([
                    idx, ans['question'], ans['category'], ans['difficulty'],
                    ans['user_answer'], ans['correct_answer'],
                    "CORRECT" if ans['is_correct'] else "INCORRECT", ans['points_awarded']
                ])

            response = Response(output.getvalue(), mimetype="text/csv")
            response.headers["Content-Disposition"] = f"attachment; filename=quiz_attempt_{attempt_id}.csv"
            return response
    finally:
        conn.close()

@app.route('/api/attempts/<int:attempt_id>/export/pdf', methods=['GET'])
def export_attempt_pdf(attempt_id):
    """Render print/PDF-optimized HTML document."""
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT qa.*, COALESCE(u.username, 'Guest') as username
                FROM quiz_attempts qa
                LEFT JOIN users u ON qa.user_id = u.id
                WHERE qa.id = %s""",
                (attempt_id,)
            )
            attempt = cursor.fetchone()
            if not attempt:
                return "Quiz attempt not found", 404

            cursor.execute(
                """SELECT aa.*, q.question, q.correct_answer, q.explanation, q.category, q.difficulty
                FROM attempt_answers aa
                JOIN questions q ON aa.question_id = q.id
                WHERE aa.attempt_id = %s
                ORDER BY aa.id ASC""",
                (attempt_id,)
            )
            answers = cursor.fetchall()

            return render_template('pdf_report.html', attempt=attempt, answers=answers)
    finally:
        conn.close()

# -------------------------------------------------------------
# Admin Question Management & S3 Image Upload (CRUD)
# -------------------------------------------------------------
@app.route('/api/admin/questions/upload-image', methods=['POST'])
@admin_required
def admin_upload_question_image():
    """Upload an optional illustration image for a question to Amazon S3 (or local fallback)."""
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
        return jsonify({'error': 'Allowed image formats: JPG, PNG, WEBP, GIF'}), 400

    file_bytes = file.read()
    filename = secure_filename(file.filename)
    unique_key = f"questions/{uuid.uuid4().hex[:12]}_{filename}"

    s3_key, image_url = save_file_s3_or_local(file_bytes, unique_key, file.content_type)
    app.logger.info("[ADMIN_IMAGE_UPLOAD] Question image uploaded: %s", s3_key)

    return jsonify({'image_s3_key': s3_key, 'image_url': image_url}), 201

@app.route('/api/admin/questions', methods=['GET'])
@admin_required
def admin_get_questions():
    category = request.args.get('category')
    search = request.args.get('search', '').strip()

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            query = "SELECT * FROM questions WHERE 1=1"
            params = []
            if category and category != 'All':
                query += " AND category = %s"
                params.append(category)
            if search:
                query += " AND (question LIKE %s OR category LIKE %s)"
                params.extend([f"%{search}%", f"%{search}%"])

            query += " ORDER BY id DESC"
            cursor.execute(query, tuple(params))
            questions = cursor.fetchall()

            for q in questions:
                if q.get('image_s3_key'):
                    q['image_url'] = generate_presigned_url(q['image_s3_key'], expires_in=900)

            return jsonify({'questions': questions, 'count': len(questions)}), 200
    finally:
        conn.close()

@app.route('/api/admin/questions', methods=['POST'])
@admin_required
def admin_create_question():
    data = request.get_json() or {}
    category = (data.get('category') or '').strip()
    difficulty = (data.get('difficulty') or 'medium').strip().lower()
    question = (data.get('question') or '').strip()
    option_a = (data.get('option_a') or '').strip()
    option_b = (data.get('option_b') or '').strip()
    option_c = (data.get('option_c') or '').strip()
    option_d = (data.get('option_d') or '').strip()
    correct_answer = (data.get('correct_answer') or '').strip()
    hint = (data.get('hint') or '').strip()
    explanation = (data.get('explanation') or '').strip()
    image_s3_key = (data.get('image_s3_key') or '').strip() or None

    if not all([category, question, option_a, option_b, option_c, option_d, correct_answer]):
        return jsonify({'error': 'Category, question, 4 options, and correct answer are required'}), 400

    if correct_answer not in [option_a, option_b, option_c, option_d]:
        return jsonify({'error': 'Correct answer must exactly match one of the four options'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO questions
                (category, difficulty, question, option_a, option_b, option_c, option_d, correct_answer, hint, explanation, image_s3_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (category, difficulty, question, option_a, option_b, option_c, option_d, correct_answer, hint, explanation, image_s3_key)
            )
            q_id = cursor.lastrowid
            conn.commit()
            app.logger.info("[ADMIN_CREATE_QUESTION] Question #%s created: %s", q_id, question[:40])
            return jsonify({'message': 'Question created successfully', 'id': q_id}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/questions/<int:q_id>', methods=['PUT'])
@admin_required
def admin_update_question(q_id):
    data = request.get_json() or {}
    category = (data.get('category') or '').strip()
    difficulty = (data.get('difficulty') or 'medium').strip().lower()
    question = (data.get('question') or '').strip()
    option_a = (data.get('option_a') or '').strip()
    option_b = (data.get('option_b') or '').strip()
    option_c = (data.get('option_c') or '').strip()
    option_d = (data.get('option_d') or '').strip()
    correct_answer = (data.get('correct_answer') or '').strip()
    hint = (data.get('hint') or '').strip()
    explanation = (data.get('explanation') or '').strip()
    image_s3_key = (data.get('image_s3_key') or '').strip() or None

    if not all([category, question, option_a, option_b, option_c, option_d, correct_answer]):
        return jsonify({'error': 'Category, question, 4 options, and correct answer are required'}), 400

    if correct_answer not in [option_a, option_b, option_c, option_d]:
        return jsonify({'error': 'Correct answer must match one of the 4 options'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """UPDATE questions
                SET category = %s, difficulty = %s, question = %s, option_a = %s, option_b = %s,
                    option_c = %s, option_d = %s, correct_answer = %s, hint = %s, explanation = %s,
                    image_s3_key = COALESCE(%s, image_s3_key)
                WHERE id = %s""",
                (category, difficulty, question, option_a, option_b, option_c, option_d, correct_answer, hint, explanation, image_s3_key, q_id)
            )
            conn.commit()
            app.logger.info("[ADMIN_UPDATE_QUESTION] Question #%s updated", q_id)
            return jsonify({'message': 'Question updated successfully'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/questions/<int:q_id>', methods=['DELETE'])
@admin_required
def admin_delete_question(q_id):
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM questions WHERE id = %s", (q_id,))
            conn.commit()
            app.logger.info("[ADMIN_DELETE_QUESTION] Question #%s deleted", q_id)
            return jsonify({'message': 'Question deleted successfully'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# -------------------------------------------------------------
# Web Page Routing
# -------------------------------------------------------------
@app.route('/')
@app.route('/quiz')
@app.route('/leaderboard')
@app.route('/profile')
@app.route('/admin')
def index():
    """Main Single Page Application container."""
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def legacy_submit():
    flash('Please use the modern Quiz Generator interface!')
    return redirect(url_for('index'))

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)