"""
aws_services.py - AWS Integration & Local Fallback Management Module
Encapsulates Amazon S3, Amazon SNS, Amazon CloudWatch Logs, and Amazon RDS diagnostics.
Supports seamless switching between Live AWS (USE_AWS=true) and Local Fallbacks (USE_AWS=false).
NEVER requires hard-coded credentials; relies on EC2 IAM Instance Profile in production.
"""

import os
import io
import time
import logging
from datetime import datetime
from dotenv import load_dotenv

# Load environment configuration
load_dotenv()

# Logger setup
logger = logging.getLogger("quizgen")
logger.setLevel(logging.INFO)

# Configuration Flags & AWS Parameters
USE_AWS = os.getenv("USE_AWS", "false").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "quizgen-results-bucket")
SNS_TOPIC_ARN = os.getenv("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:quiz-score-notifications")
CLOUDWATCH_LOG_GROUP = os.getenv("CLOUDWATCH_LOG_GROUP", "QuizGen-App-Logs")

# Local storage fallback directory
LOCAL_UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(LOCAL_UPLOADS_DIR, exist_ok=True)

# Lazy Boto3 clients
_s3_client = None
_sns_client = None
_cw_client = None

def get_s3_client():
    global _s3_client
    if _s3_client is None and USE_AWS:
        import boto3
        _s3_client = boto3.client("s3", region_name=AWS_REGION)
    return _s3_client

def get_sns_client():
    global _sns_client
    if _sns_client is None and USE_AWS:
        import boto3
        _sns_client = boto3.client("sns", region_name=AWS_REGION)
    return _sns_client

def get_cw_client():
    global _cw_client
    if _cw_client is None and USE_AWS:
        import boto3
        _cw_client = boto3.client("logs", region_name=AWS_REGION)
    return _cw_client

# -------------------------------------------------------------
# 1. CloudWatch Application Logging Setup
# -------------------------------------------------------------
def setup_cloudwatch_logging(flask_app):
    """
    Configure application logging to CloudWatch Logs (when USE_AWS=true)
    or console StreamHandler fallback (when USE_AWS=false).
    """
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [QuizGen] %(message)s")

    # Clear existing handlers to avoid duplicates
    flask_app.logger.handlers.clear()

    if USE_AWS:
        try:
            import watchtower
            import boto3

            logs_client = boto3.client("logs", region_name=AWS_REGION)
            cw_handler = watchtower.CloudWatchLogHandler(
                log_group_name=CLOUDWATCH_LOG_GROUP,
                boto3_client=logs_client,
                send_interval=5,
                create_log_group=True
            )
            cw_handler.setFormatter(formatter)
            flask_app.logger.addHandler(cw_handler)
            flask_app.logger.info("CloudWatch logging initialized successfully in log group: %s", CLOUDWATCH_LOG_GROUP)
            print(f"[AWS CloudWatch] Attached CloudWatchLogHandler to log group: {CLOUDWATCH_LOG_GROUP}")
        except Exception as e:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            flask_app.logger.addHandler(console_handler)
            flask_app.logger.warning("Failed to initialize CloudWatch handler (%s); fallback to console logging", e)
    else:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        flask_app.logger.addHandler(console_handler)
        flask_app.logger.info("Local console logging initialized (USE_AWS=false)")

# -------------------------------------------------------------
# 2. S3 Storage & Pre-signed URLs (With Local Fallback)
# -------------------------------------------------------------
def save_file_s3_or_local(file_bytes, relative_key, content_type="application/octet-stream"):
    """
    Save or upload a file (PDF, CSV, Image) to Amazon S3 when USE_AWS=true,
    or to the local 'uploads/' folder when USE_AWS=false.
    Returns: (stored_key, public_or_local_url)
    """
    if USE_AWS:
        try:
            s3 = get_s3_client()
            s3.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=relative_key,
                Body=file_bytes,
                ContentType=content_type
            )
            presigned_url = generate_presigned_url(relative_key, expires_in=900)
            logger.info("[S3_UPLOAD] Successfully uploaded %s to S3 bucket %s", relative_key, S3_BUCKET_NAME)
            return relative_key, presigned_url
        except Exception as e:
            logger.error("[S3_ERROR] Upload failed for %s: %s. Using local fallback.", relative_key, e)
            # Fall through to local fallback

    # Local Fallback
    local_path = os.path.join(LOCAL_UPLOADS_DIR, relative_key)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(file_bytes)

    local_url = f"/downloads/{relative_key}"
    logger.info("[LOCAL_STORAGE] Saved %s to local uploads directory: %s", relative_key, local_url)
    return relative_key, local_url

def generate_presigned_url(s3_key, expires_in=900, original_filename=None):
    """
    Generate an S3 pre-signed URL with 15-minute expiry (900s),
    or return the local file download path if in fallback mode.
    """
    if USE_AWS:
        try:
            s3 = get_s3_client()
            params = {"Bucket": S3_BUCKET_NAME, "Key": s3_key}
            if original_filename:
                params["ResponseContentDisposition"] = f'attachment; filename="{original_filename}"'

            url = s3.generate_presigned_url("get_object", Params=params, ExpiresIn=expires_in)
            return url
        except Exception as e:
            logger.error("[S3_PRESIGN_ERROR] Could not generate presigned URL: %s", e)
            return f"/downloads/{s3_key}"

    return f"/downloads/{s3_key}"

# -------------------------------------------------------------
# 3. Amazon SNS Topic Publishing & Email Subscription
# -------------------------------------------------------------
def publish_quiz_result_sns(username, category, difficulty, score, accuracy, rank=None):
    """
    Publish quiz completion stats to the Amazon SNS topic.
    Logs to console if USE_AWS=false.
    """
    subject = f"Quiz Result: {username} scored {score} pts in {category}!"
    message = (
        f"Online GK Quiz Generator - Achievement Notification\n"
        f"---------------------------------------------------\n"
        f"Player   : {username}\n"
        f"Category : {category} ({difficulty.capitalize()})\n"
        f"Score    : {score} Points\n"
        f"Accuracy : {accuracy}%\n"
        f"Rank     : #{rank if rank else 'N/A'}\n"
        f"Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"---------------------------------------------------\n"
        f"Challenge yourself at: http://quizgen.io\n"
    )

    if USE_AWS:
        try:
            sns = get_sns_client()
            response = sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=subject[:100],  # SNS subject limit is 100 chars
                Message=message
            )
            msg_id = response.get("MessageId")
            logger.info("[SNS_PUBLISH] Published result for %s to %s (MsgId: %s)", username, SNS_TOPIC_ARN, msg_id)
            return True, msg_id
        except Exception as e:
            logger.error("[SNS_ERROR] Failed to publish message: %s", e)
            return False, str(e)
    else:
        print("\n" + "-" * 55)
        print("[LOCAL SNS MOCK] Publishing Score Notification to SNS Topic:")
        print(f"Topic ARN : {SNS_TOPIC_ARN}")
        print(f"Subject   : {subject}")
        print(f"Message   :\n{message}")
        print("-" * 55 + "\n")
        logger.info("[SNS_LOCAL_MOCK] Published score alert for %s", username)
        return True, "mock-sns-message-id-local"

def subscribe_email_sns(email):
    """
    Subscribe user email address to the SNS topic for score notifications.
    """
    if USE_AWS:
        try:
            sns = get_sns_client()
            response = sns.subscribe(
                TopicArn=SNS_TOPIC_ARN,
                Protocol="email",
                Endpoint=email
            )
            sub_arn = response.get("SubscriptionArn")
            logger.info("[SNS_SUBSCRIBE] Subscribed %s to %s (SubArn: %s)", email, SNS_TOPIC_ARN, sub_arn)
            return True, "Subscription email sent! Please check your inbox and confirm."
        except Exception as e:
            logger.error("[SNS_SUBSCRIBE_ERROR] Failed to subscribe %s: %s", email, e)
            return False, str(e)
    else:
        print(f"\n[LOCAL SNS MOCK] Subscribed email '{email}' to SNS Topic: {SNS_TOPIC_ARN}")
        return True, "Subscribed successfully! (Simulated in Local Mode)"

# -------------------------------------------------------------
# 4. AWS Health & Connectivity Diagnostics (/aws-status)
# -------------------------------------------------------------
def get_aws_connectivity_status(db_conn_func):
    """
    Check live connectivity and latency for Amazon RDS, S3, SNS, and CloudWatch.
    Returns status dictionary for the /aws-status admin dashboard.
    """
    results = {
        "mode": "AWS Cloud" if USE_AWS else "Local Fallback",
        "use_aws": USE_AWS,
        "region": AWS_REGION,
        "services": {}
    }

    # 1. Amazon RDS MySQL
    rds_start = time.time()
    try:
        conn = db_conn_func()
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION() AS ver, DATABASE() AS db_name;")
            row = cur.fetchone()
        conn.close()
        rds_ms = round((time.time() - rds_start) * 1000, 1)
        results["services"]["rds"] = {
            "name": "Amazon RDS (MySQL)",
            "status": "healthy",
            "latency_ms": rds_ms,
            "details": f"Connected to {row['db_name']} (MySQL {row['ver']})",
            "endpoint": f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', 3306)}"
        }
    except Exception as e:
        results["services"]["rds"] = {
            "name": "Amazon RDS (MySQL)",
            "status": "unhealthy",
            "latency_ms": None,
            "details": str(e),
            "endpoint": f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', 3306)}"
        }

    # 2. Amazon S3
    if USE_AWS:
        s3_start = time.time()
        try:
            s3 = get_s3_client()
            s3.head_bucket(Bucket=S3_BUCKET_NAME)
            s3_ms = round((time.time() - s3_start) * 1000, 1)
            results["services"]["s3"] = {
                "name": "Amazon S3",
                "status": "healthy",
                "latency_ms": s3_ms,
                "details": f"Bucket '{S3_BUCKET_NAME}' verified & accessible",
                "resource": S3_BUCKET_NAME
            }
        except Exception as e:
            results["services"]["s3"] = {
                "name": "Amazon S3",
                "status": "unhealthy",
                "latency_ms": None,
                "details": str(e),
                "resource": S3_BUCKET_NAME
            }
    else:
        results["services"]["s3"] = {
            "name": "Amazon S3",
            "status": "fallback",
            "latency_ms": 0.5,
            "details": f"Local storage active at uploads/ (Target Bucket: {S3_BUCKET_NAME})",
            "resource": "Local uploads/ directory"
        }

    # 3. Amazon SNS
    if USE_AWS:
        sns_start = time.time()
        try:
            sns = get_sns_client()
            sns.get_topic_attributes(TopicArn=SNS_TOPIC_ARN)
            sns_ms = round((time.time() - sns_start) * 1000, 1)
            results["services"]["sns"] = {
                "name": "Amazon SNS",
                "status": "healthy",
                "latency_ms": sns_ms,
                "details": "Topic verified and ready for notifications",
                "resource": SNS_TOPIC_ARN
            }
        except Exception as e:
            results["services"]["sns"] = {
                "name": "Amazon SNS",
                "status": "unhealthy",
                "latency_ms": None,
                "details": str(e),
                "resource": SNS_TOPIC_ARN
            }
    else:
        results["services"]["sns"] = {
            "name": "Amazon SNS",
            "status": "fallback",
            "latency_ms": 0.3,
            "details": f"Local mock logger active (Target Topic: {SNS_TOPIC_ARN})",
            "resource": "Console Log Emitter"
        }

    # 4. Amazon CloudWatch Logs
    if USE_AWS:
        cw_start = time.time()
        try:
            cw = get_cw_client()
            cw.describe_log_groups(logGroupNamePrefix=CLOUDWATCH_LOG_GROUP)
            cw_ms = round((time.time() - cw_start) * 1000, 1)
            results["services"]["cloudwatch"] = {
                "name": "Amazon CloudWatch Logs",
                "status": "healthy",
                "latency_ms": cw_ms,
                "details": f"Log Group '{CLOUDWATCH_LOG_GROUP}' active via watchtower",
                "resource": CLOUDWATCH_LOG_GROUP
            }
        except Exception as e:
            results["services"]["cloudwatch"] = {
                "name": "Amazon CloudWatch Logs",
                "status": "unhealthy",
                "latency_ms": None,
                "details": str(e),
                "resource": CLOUDWATCH_LOG_GROUP
            }
    else:
        results["services"]["cloudwatch"] = {
            "name": "Amazon CloudWatch Logs",
            "status": "fallback",
            "latency_ms": 0.2,
            "details": f"Local StreamHandler logging active (Target Group: {CLOUDWATCH_LOG_GROUP})",
            "resource": "Local StreamHandler"
        }

    return results
