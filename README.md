# ⚡ Online GK Quiz Generator & Arena
### Production-Ready Flask + MySQL Application with AWS Cloud Integration

An enterprise-grade, gamified **General Knowledge (GK) Online Quiz Generator** built with **Python Flask**, **MySQL**, and modern **Vanilla HTML/CSS/JavaScript**. Architected to run seamlessly either **100% locally** (with graceful fallbacks) or on **Amazon Web Services (AWS)** using Amazon EC2, Amazon RDS, Amazon S3, Amazon SNS, and Amazon CloudWatch.

---

## 🚀 Key Features

### 🎮 Gamified Quiz Arena
- **Dynamic Quiz Generator:** Pick from 8 distinct GK categories (*History, Geography, Science, Sports, Politics, Current Affairs, Entertainment, Technology*), select difficulty (*Easy, Medium, Hard, All*), and length (*5, 10, 15, 20 questions*).
- **Life System (3 Hearts):** Players start with 3 lives. Wrong answers or 30-second timeouts cost a heart.
- **Interactive Lifelines:**
  - `50:50` eliminates two incorrect choices.
  - `Text Hint` delivers a curated historical/scientific clue.
  - `Skip Question` bypasses a difficult prompt once per attempt.
- **Dynamic Streak Multipliers:** Consecutive correct answers build fire streaks with bonus points.
- **Synthesized Web Audio FX:** Custom chimes, ticking clocks, buzzing alerts, game over notes, and victory fanfare powered entirely via the Web Audio API without heavy external audio files.
- **Dual Visual Themes:** Seamless Dark Mode and Light Mode switching with persistent preference storage.

### 🏆 Leaderboards & User Profiles
- **Hall of Fame:** Category-filtered top-10 leaderboard ranking players by total score, accuracy, and speed.
- **Player History:** Detailed audit trail of past quiz attempts with score analytics.
- **Direct Exports:** Instant CSV data export and print-ready PDF certificate generation.

### 🛡️ Admin Management
- **Full Question CRUD:** Search, filter, add, edit, and delete questions with real-time category counter updates.
- **S3 Illustration Upload:** Upload question images directly to Amazon S3 (or local storage fallback).

---

## ☁️ AWS Cloud Architecture & Local Fallbacks

The application is controlled by a single environment toggle: `USE_AWS=true` or `USE_AWS=false`.

| Component | In AWS Cloud Mode (`USE_AWS=true`) | In Local Fallback Mode (`USE_AWS=false`) |
| :--- | :--- | :--- |
| **Database** | **Amazon RDS MySQL** (Multi-AZ / Single-AZ) | **Local MySQL Instance** |
| **File Storage** | **Amazon S3** (`s3://bucket/results/<user_id>/...`) | **Local Directory** (`uploads/results/...`) |
| **Download Links** | **15-Minute S3 Pre-Signed URLs** | **Local Web Server File Routes** |
| **Notifications** | **Amazon SNS** (Email alerts on quiz completion) | **Console Logger Mock Emitter** |
| **Observability** | **Amazon CloudWatch Logs** (`watchtower`) | **Standard Stream & Rotating Logger** |
| **Credentials** | **EC2 IAM Role** (Zero hardcoded secrets) | **Local `.env` File** |

### Live AWS Diagnostic Dashboard
Navigate to `/aws-status` in your browser for a real-time health indicator checking RDS latency, S3 bucket access, SNS topic status, and CloudWatch stream connectivity.

---

## 🛠️ Tech Stack

- **Backend:** Python 3.10+, Flask, Gunicorn
- **Database Driver:** PyMySQL, Cryptography
- **AWS SDK:** `boto3`, `watchtower`
- **Frontend:** HTML5, Modern CSS3 (CSS Variables, Flexbox, CSS Grid), Vanilla ES6 JavaScript
- **Styling & UI:** Bootstrap 5.3, Font Awesome 6.4, Inter & Outfit Google Fonts
- **Audio:** Web Audio API (native browser synthesizer)

---

## 💻 Local Quickstart

### 1. Clone & Set Up Virtual Environment

```bash
git clone https://github.com/simboli/quiz-flask-app.git
cd quiz-flask-app

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Linux / macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy the example `.env` file:
```bash
cp .env.example .env
```

Edit `.env` for your local MySQL database:
```env
USE_AWS=false
AWS_REGION=us-east-1

DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=quiz-app

SECRET_KEY=supersecretkey-local-development
```

### 3. Provision Database & Seed 64 Questions

Run the automated provisioning script to create the schema and populate all 64 questions:
```bash
python setup_db.py
```
*(Or use `python setup_rds.py` when pointing to a remote Amazon RDS instance)*

Default seeded credentials:
- **Admin:** `admin` / `admin123`
- **Player:** `player1` / `player123`

### 4. Run the Application

```bash
python app.py
```
Open **`http://127.0.0.1:5000`** in your browser.

---

## 📖 AWS Deployment Guide

For full step-by-step instructions on provisioning:
- **EC2 Ubuntu 22.04 LTS**
- **RDS MySQL Database with VPC Security Groups**
- **S3 Bucket & SNS Topics**
- **IAM Instance Profile JSON Policies**
- **Gunicorn Systemd Unit (`quizgen.service`)**
- **Nginx Reverse Proxy & Let's Encrypt SSL**

👉 **Read the comprehensive [DEPLOY_AWS.md](DEPLOY_AWS.md) guide.**

---

## 🔌 API Endpoints Reference

### Public & Game Engine APIs
- `GET /health` - Health check and environment mode status
- `GET /aws-status` - AWS service connectivity dashboard
- `GET /api/aws/status` - JSON diagnostic check of RDS, S3, SNS, CloudWatch
- `GET /api/categories` - Available categories and question counts
- `POST /api/quiz/start` - Initialize customized quiz attempt
- `GET /api/quiz/<attempt_id>/current` - Retrieve current question
- `POST /api/quiz/<attempt_id>/hint` - Request 50:50 or text hint
- `POST /api/quiz/<attempt_id>/skip` - Skip current question
- `POST /api/quiz/<attempt_id>/answer` - Submit answer and receive instant feedback
- `GET /api/quiz/<attempt_id>/result` - Retrieve quiz summary, question review, and S3 pre-signed download URLs
- `GET /api/leaderboard?category=<cat>` - Top 10 leaderboard rankings

### Authentication & User APIs
- `POST /api/auth/register` - Create user account
- `POST /api/auth/login` - User sign-in
- `POST /api/auth/logout` - User sign-out
- `GET /api/auth/me` - Current session profile
- `GET /api/user/history` - User quiz attempt history & statistics
- `POST /api/user/subscribe-sns` - Subscribe email to Amazon SNS score alerts

### Admin Question APIs (Protected)
- `GET /api/admin/questions` - Search and filter question bank
- `POST /api/admin/questions` - Add new question
- `PUT /api/admin/questions/<id>` - Update existing question
- `DELETE /api/admin/questions/<id>` - Delete question
- `POST /api/admin/questions/upload-image` - Upload question illustration to S3

---

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
