-- Database Schema for Online Quiz Generator (AWS RDS MySQL & Local Compatible)

-- Users Table
CREATE TABLE IF NOT EXISTS `users` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `username` VARCHAR(64) NOT NULL UNIQUE,
  `email` VARCHAR(120) NOT NULL UNIQUE,
  `password_hash` VARCHAR(255) NOT NULL,
  `role` VARCHAR(20) NOT NULL DEFAULT 'user',
  `sns_subscribed` TINYINT(1) NOT NULL DEFAULT 0,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Questions Table
CREATE TABLE IF NOT EXISTS `questions` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `category` VARCHAR(50) NOT NULL,
  `difficulty` VARCHAR(20) NOT NULL, -- 'easy', 'medium', 'hard'
  `question` TEXT NOT NULL,
  `option_a` VARCHAR(255) NOT NULL,
  `option_b` VARCHAR(255) NOT NULL,
  `option_c` VARCHAR(255) NOT NULL,
  `option_d` VARCHAR(255) NOT NULL,
  `correct_answer` VARCHAR(255) NOT NULL,
  `hint` VARCHAR(255) NOT NULL,
  `explanation` TEXT,
  `image_s3_key` VARCHAR(255) NULL,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Quiz Attempts Table
CREATE TABLE IF NOT EXISTS `quiz_attempts` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `user_id` INT NULL,
  `session_token` VARCHAR(64) NOT NULL UNIQUE,
  `category` VARCHAR(50) NOT NULL,
  `difficulty` VARCHAR(20) NOT NULL,
  `total_questions` INT NOT NULL,
  `current_question_index` INT NOT NULL DEFAULT 0,
  `score` INT NOT NULL DEFAULT 0,
  `streak` INT NOT NULL DEFAULT 0,
  `max_streak` INT NOT NULL DEFAULT 0,
  `hearts_left` INT NOT NULL DEFAULT 3,
  `hints_5050_left` INT NOT NULL DEFAULT 1,
  `hints_text_left` INT NOT NULL DEFAULT 1,
  `skips_left` INT NOT NULL DEFAULT 1,
  `status` VARCHAR(20) NOT NULL DEFAULT 'in_progress', -- 'in_progress', 'completed', 'game_over'
  `time_taken_seconds` INT NOT NULL DEFAULT 0,
  `accuracy` FLOAT NOT NULL DEFAULT 0.0,
  `questions_order` TEXT NOT NULL,
  `pdf_s3_key` VARCHAR(255) NULL,
  `csv_s3_key` VARCHAR(255) NULL,
  `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `completed_at` DATETIME NULL,
  CONSTRAINT `fk_attempt_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Attempt Answers Table
CREATE TABLE IF NOT EXISTS `attempt_answers` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `attempt_id` INT NOT NULL,
  `question_id` INT NOT NULL,
  `user_answer` VARCHAR(255) NULL,
  `is_correct` TINYINT(1) NOT NULL DEFAULT 0,
  `points_awarded` INT NOT NULL DEFAULT 0,
  `time_taken_seconds` INT NOT NULL DEFAULT 0,
  `hint_used` VARCHAR(20) NOT NULL DEFAULT 'none', -- 'none', '50-50', 'text'
  `is_skipped` TINYINT(1) NOT NULL DEFAULT 0,
  `answered_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT `fk_answer_attempt` FOREIGN KEY (`attempt_id`) REFERENCES `quiz_attempts` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_answer_question` FOREIGN KEY (`question_id`) REFERENCES `questions` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Legacy Tables (preserved for backwards compatibility)
CREATE TABLE IF NOT EXISTS `quiz_log` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `session_id` VARCHAR(255) DEFAULT NULL,
  `question_number` INT DEFAULT NULL,
  `question_id` INT DEFAULT NULL,
  `question` VARCHAR(255) DEFAULT NULL,
  `user_answers` TEXT,
  `correct_answers` TEXT,
  `is_correct` TINYINT(1) DEFAULT NULL,
  `first_modified_time` DATETIME DEFAULT NULL,
  `last_modified_time` DATETIME DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `session_info` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `session_id` VARCHAR(255) NOT NULL,
  `page_load_time` DATETIME NOT NULL,
  `submission_time` DATETIME NOT NULL,
  `num_questions` INT NOT NULL,
  `passing_level` FLOAT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
