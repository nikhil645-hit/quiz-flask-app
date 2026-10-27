# AWS Cloud Production Deployment Guide
## Online GK Quiz Generator (`quiz-flask-app`)

This guide walks you through deploying the **Online GK Quiz Generator** to **Amazon Web Services (AWS)** using a production-grade, highly available, and secure architecture:
- **Compute:** Amazon EC2 (Ubuntu 22.04 LTS) running Gunicorn WSGI and Nginx reverse proxy
- **Database:** Amazon RDS MySQL (Multi-AZ or Single-AZ)
- **Object Storage:** Amazon S3 for question illustrations, PDF reports, and CSV exports
- **Notification Service:** Amazon SNS for automated quiz completion alerts
- **Observability:** Amazon CloudWatch Logs for audit and telemetry
- **Security:** EC2 IAM Instance Profile (Zero hardcoded AWS credentials)

---

## 1. Architecture Overview

```text
               +------------------------------------------------+
               |                   Internet                     |
               +-----------------------+------------------------+
                                       | HTTPS (Port 443)
                                       v
                     +----------------------------------+
                     |         Nginx Reverse Proxy       |
                     |       (SSL via Let's Encrypt)     |
                     +-----------------+----------------+
                                       | Unix Socket / Port 8000
                                       v
                     +----------------------------------+
                     |         Gunicorn (3 Workers)     |
                     |         Flask Application        |
                     |       (EC2 Instance Profile)     |
                     +---+------------+------------+----+
                         |            |            |
                         v            v            v
     +-----------------------+ +--------------+ +---------------------+
     |   Amazon RDS MySQL    | |  Amazon S3   | |     Amazon SNS      |
     |   - Questions Bank    | |  - Quiz PDFs | | - Result Email      |
     |   - User Accounts     | |  - Quiz CSVs | |   Notifications     |
     |   - Attempt Logs      | |  - Images    | +---------------------+
     +-----------------------+ +-------+------+
                                       |
                                       v
                               +----------------+
                               | CloudWatch Logs|
                               | - Audit Trail  |
                               +----------------+
```

---

## 2. Prerequisites & AWS Resource Checklist

Before starting, ensure you have:
1. An active AWS Account with Administrator or PowerUser access.
2. An AWS key pair (`.pem`) created in your target region (e.g., `us-east-1`).
3. Your target domain name (optional, if setting up SSL with Let's Encrypt).

---

## 3. Step-by-Step Setup

### Step 1: Create VPC & Security Groups

Create two security groups in your VPC:

1. **`quiz-ec2-sg` (EC2 Web Server Security Group):**
   - **Inbound Rules:**
     - SSH (`22`): `My IP` (or management bastion CIDR)
     - HTTP (`80`): `0.0.0.0/0`
     - HTTPS (`443`): `0.0.0.0/0`
   - **Outbound Rules:**
     - All traffic: `0.0.0.0/0`

2. **`quiz-rds-sg` (RDS Database Security Group):**
   - **Inbound Rules:**
     - MySQL/Aurora (`3306`): Source = `quiz-ec2-sg` (Security Group ID). *Never open RDS to 0.0.0.0/0!*
   - **Outbound Rules:**
     - All traffic: `0.0.0.0/0`

---

### Step 2: Provision Amazon RDS MySQL Database

1. Open AWS Management Console > **RDS** > **Databases** > **Create database**.
2. Select **Standard create** > **MySQL**.
3. Choose Engine Version: **MySQL 8.0.x**.
4. Template: **Free Tier** (or **Production**).
5. Settings:
   - DB instance identifier: `quizgen-db`
   - Master username: `admin`
   - Master password: `<StrongPasswordHere>`
6. Instance configuration: `db.t3.micro` or `db.t4g.micro`.
7. Connectivity:
   - Virtual Private Cloud (VPC): Same VPC as EC2.
   - Public access: **No**.
   - VPC security group: Choose **`quiz-rds-sg`**.
8. Additional configuration:
   - Initial database name: `quiz_app`
9. Click **Create database**.
10. Note down the **RDS Endpoint** once available (e.g. `quizgen-db.c123456789.us-east-1.rds.amazonaws.com`).

---

### Step 3: Create Amazon S3 Bucket & Amazon SNS Topic

#### Amazon S3 Bucket:
1. Open AWS Console > **S3** > **Create bucket**.
2. Bucket name: `quizgen-storage-<unique-suffix>` (e.g., `quizgen-storage-prod-1234`).
3. AWS Region: Same as RDS/EC2 (e.g., `us-east-1`).
4. **Block Public Access**: Keep **all 4 checkboxes enabled** (Private bucket). All client downloads use signed 15-minute URLs.
5. Bucket Versioning: Enabled (recommended).
6. Click **Create bucket**.

#### Amazon SNS Topic:
1. Open AWS Console > **Amazon SNS** > **Topics** > **Create topic**.
2. Type: **Standard**.
3. Name: `quizgen-results-topic`.
4. Display name: `QuizGen Results`.
5. Click **Create topic**.
6. Copy the **Topic ARN** (e.g. `arn:aws:sns:us-east-1:123456789012:quizgen-results-topic`).

---

### Step 4: Create IAM Role with Least-Privilege Policy

Create an IAM Role for EC2 so that **no AWS Access Keys or Secrets** are stored on the server.

1. Open AWS Console > **IAM** > **Policies** > **Create policy**.
2. Switch to the **JSON** tab and paste the following policy:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "QuizGenS3BucketAccess",
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:DeleteObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::quizgen-storage-*",
                "arn:aws:s3:::quizgen-storage-*/*"
            ]
        },
        {
            "Sid": "QuizGenSNSPublishAccess",
            "Effect": "Allow",
            "Action": [
                "sns:Publish",
                "sns:Subscribe"
            ],
            "Resource": "arn:aws:sns:*:*:quizgen-*"
        },
        {
            "Sid": "QuizGenCloudWatchLogsAccess",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "logs:DescribeLogStreams"
            ],
            "Resource": "arn:aws:logs:*:*:log-group:/quiz-flask-app/*"
        }
    ]
}
```

3. Name the policy: `QuizGenAppPolicy`.
4. Go to **Roles** > **Create role**.
5. Trusted entity type: **AWS service** > Use case: **EC2**.
6. Attach permissions: Select `QuizGenAppPolicy`.
7. Role name: `QuizGenEC2Role`. Click **Create role**.

---

### Step 5: Launch EC2 Instance & Attach IAM Role

1. Go to AWS Console > **EC2** > **Launch instance**.
2. Name: `quizgen-web-server`.
3. AMI: **Ubuntu Server 22.04 LTS (HVM), SSD Volume Type**.
4. Instance type: `t3.micro` or `t3.small`.
5. Key pair: Select your existing key pair.
6. Network settings:
   - Select your VPC.
   - Assign public IP: **Enable**.
   - Select existing security group: `quiz-ec2-sg`.
7. Advanced details:
   - IAM instance profile: Select **`QuizGenEC2Role`**.
8. Click **Launch instance**.

---

### Step 6: Connect to EC2 and Configure Application

SSH into your Ubuntu server:
```bash
ssh -i /path/to/your-key.pem ubuntu@<EC2-PUBLIC-IP>
```

#### 1. Update OS and Install System Packages:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git nginx
```

#### 2. Clone the Repository:
```bash
cd /var/www
sudo git clone https://github.com/your-username/quiz-flask-app.git quizapp
sudo chown -R ubuntu:ubuntu /var/www/quizapp
cd /var/www/quizapp
```

#### 3. Setup Virtual Environment:
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

#### 4. Configure Production Environment Variables:
Create `/var/www/quizapp/.env`:
```bash
nano .env
```

Paste your production configuration:
```env
# Toggle AWS Cloud Services
USE_AWS=true
AWS_REGION=us-east-1

# Amazon RDS MySQL Configuration
DB_HOST=quizgen-db.c123456789.us-east-1.rds.amazonaws.com
DB_PORT=3306
DB_USER=admin
DB_PASSWORD=YourStrongPasswordHere
DB_NAME=quiz_app

# Amazon S3 Bucket
S3_BUCKET_NAME=quizgen-storage-prod-1234

# Amazon SNS Topic
SNS_TOPIC_ARN=arn:aws:sns:us-east-1:123456789012:quizgen-results-topic

# Amazon CloudWatch Logs
CLOUDWATCH_LOG_GROUP=/quiz-flask-app/production

# Application Security
SECRET_KEY=generate-a-strong-random-hex-string-for-flask-session
PORT=5000
```

Secure the permissions:
```bash
chmod 600 .env
```

#### 5. Run Database Setup Script:
Run `setup_rds.py` to create tables and seed 64 GK questions:
```bash
python setup_rds.py
```
*Expected output:*
```text
Connecting to RDS MySQL at quizgen-db.c123456789.us-east-1.rds.amazonaws.com:3306...
Successfully connected to database quiz_app!
Executing DDL schema statements...
Tables verified/created successfully.
Default admin & player accounts initialized.
Successfully seeded 64 GK questions into RDS!
=== RDS Provisioning & Seeding Completed Successfully ===
```

---

### Step 7: Configure Gunicorn and Systemd Service

Create systemd service unit file `/etc/systemd/system/quizgen.service`:
```bash
sudo nano /etc/systemd/system/quizgen.service
```

Paste the following configuration:
```ini
[Unit]
Description=Gunicorn instance to serve Online GK Quiz Generator
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/var/www/quizapp
Environment="PATH=/var/www/quizapp/venv/bin"
ExecStart=/var/www/quizapp/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 app:app --access-logfile /var/log/quizgen_access.log --error-logfile /var/log/quizgen_error.log

Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl start quizgen
sudo systemctl enable quizgen
sudo systemctl status quizgen
```

---

### Step 8: Configure Nginx as Reverse Proxy

Create Nginx site configuration `/etc/nginx/sites-available/quizgen`:
```bash
sudo nano /etc/nginx/sites-available/quizgen
```

Paste the following Nginx block:
```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com; # Or replace with EC2 Public IP

    client_max_body_size 16M;

    location /static {
        alias /var/www/quizapp/static;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_read_timeout 120s;
    }
}
```

Enable the configuration and restart Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/quizgen /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

---

### Step 9: Setup SSL Certificate with Let's Encrypt (Certbot)

If using a custom domain:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```
Certbot automatically configures HTTPS and sets up auto-renewal cron tasks.

---

## 4. Verification and Health Checks

Verify your deployment by checking the endpoints in your browser:

1. **Application Interface:**
   - `http://<EC2-PUBLIC-IP>/`
2. **Standard Health Check:**
   - `http://<EC2-PUBLIC-IP>/health`
   - *Expected Response:* `{"status": "healthy", "service": "Online GK Quiz Generator", "mode": "AWS"}`
3. **AWS Live Cloud Diagnostic Dashboard:**
   - `http://<EC2-PUBLIC-IP>/aws-status`
   - Live visual indicator confirming active connections to:
     - Amazon RDS MySQL (Ping & latency)
     - Amazon S3 Bucket (`quizgen-storage-...`)
     - Amazon SNS Topic (`quizgen-results-topic`)
     - Amazon CloudWatch Log Group (`/quiz-flask-app/production`)

---

## 5. Maintenance & Troubleshooting

| Issue | Resolution |
| :--- | :--- |
| **Gunicorn fails to start** | Check service logs: `sudo journalctl -u quizgen -n 50 --no-pager` |
| **RDS connection timeout** | Verify RDS Security Group has inbound rule for port 3306 from `quiz-ec2-sg` |
| **S3 Access Denied (403)** | Confirm `QuizGenEC2Role` is attached to EC2 and policy permits bucket actions |
| **SNS Emails not received** | Recipient must click "Confirm Subscription" link sent by AWS SNS |
| **CloudWatch logs missing** | Ensure `CLOUDWATCH_LOG_GROUP` exists or IAM role has `logs:CreateLogGroup` permission |
