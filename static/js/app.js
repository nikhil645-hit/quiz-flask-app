/**
 * Online GK Quiz Generator - Core Application Controller
 * Handles Audio Synth, REST API Fetch, Game Loop, Timer, Lifelines, Auth, and Views
 */

// -------------------------------------------------------------
// Web Audio API Synthesizer (Zero External Dependencies)
// -------------------------------------------------------------
class SoundController {
    constructor() {
        this.ctx = null;
        this.muted = localStorage.getItem('quiz_sound_muted') === 'true';
    }

    init() {
        if (!this.ctx) {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            this.ctx = new AudioContext();
        }
        if (this.ctx.state === 'suspended') {
            this.ctx.resume();
        }
    }

    toggleMute() {
        this.muted = !this.muted;
        localStorage.setItem('quiz_sound_muted', this.muted);
        return this.muted;
    }

    playTone(freq, type, duration, gainLevel = 0.15) {
        if (this.muted) return;
        this.init();
        try {
            const osc = this.ctx.createOscillator();
            const gain = this.ctx.createGain();
            osc.type = type;
            osc.frequency.setValueAtTime(freq, this.ctx.currentTime);
            gain.gain.setValueAtTime(gainLevel, this.ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.0001, this.ctx.currentTime + duration);
            osc.connect(gain);
            gain.connect(this.ctx.destination);
            osc.start();
            osc.stop(this.ctx.currentTime + duration);
        } catch (e) {
            console.debug('Audio error:', e);
        }
    }

    playCorrect() {
        if (this.muted) return;
        this.init();
        // Cheerful ascending two-tone chime
        this.playTone(523.25, 'sine', 0.15, 0.2); // C5
        setTimeout(() => this.playTone(659.25, 'sine', 0.3, 0.2), 120); // E5
    }

    playWrong() {
        if (this.muted) return;
        this.init();
        // Low buzzer
        this.playTone(180, 'sawtooth', 0.25, 0.25);
        setTimeout(() => this.playTone(140, 'sawtooth', 0.35, 0.25), 140);
    }

    playTick() {
        if (this.muted) return;
        this.playTone(880, 'triangle', 0.05, 0.04);
    }

    playGameOver() {
        if (this.muted) return;
        this.init();
        const notes = [300, 260, 220, 180];
        notes.forEach((freq, idx) => {
            setTimeout(() => this.playTone(freq, 'sawtooth', 0.3, 0.2), idx * 160);
        });
    }

    playCelebration() {
        if (this.muted) return;
        this.init();
        const notes = [523.25, 659.25, 783.99, 1046.50];
        notes.forEach((freq, idx) => {
            setTimeout(() => this.playTone(freq, 'triangle', 0.25, 0.2), idx * 120);
        });
    }
}

// -------------------------------------------------------------
// App State
// -------------------------------------------------------------
const App = {
    sound: new SoundController(),
    user: null,
    currentAttemptId: null,
    currentQuestion: null,
    timerInterval: null,
    timeRemaining: 30,
    timeSpent: 0,
    currentHintUsed: 'none', // 'none', '50-50', 'text', 'both'
    selectedCategory: 'All',
    selectedDifficulty: 'all',
    selectedNumQuestions: 10,

    init() {
        this.initTheme();
        this.initSoundButton();
        this.checkAuth();
        this.loadCategories();
        this.setupEventListeners();
        this.routeFromUrl();
    },

    // Theme Management
    initTheme() {
        const savedTheme = localStorage.getItem('quiz_theme') || 'dark';
        document.documentElement.setAttribute('data-theme', savedTheme);
        this.updateThemeIcons(savedTheme);
    },

    toggleTheme() {
        const current = document.documentElement.getAttribute('data-theme') || 'light';
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('quiz_theme', next);
        this.updateThemeIcons(next);
    },

    updateThemeIcons(theme) {
        const btn = document.getElementById('theme-toggle-btn');
        if (btn) {
            btn.innerHTML = theme === 'dark' 
                ? '<i class="fa-solid fa-sun text-warning"></i>' 
                : '<i class="fa-solid fa-moon text-primary"></i>';
        }
    },

    // Sound Management
    initSoundButton() {
        this.updateSoundIcon();
    },

    toggleSound() {
        const muted = this.sound.toggleMute();
        this.updateSoundIcon();
    },

    updateSoundIcon() {
        const btn = document.getElementById('sound-toggle-btn');
        if (btn) {
            btn.innerHTML = this.sound.muted 
                ? '<i class="fa-solid fa-volume-xmark text-muted"></i>' 
                : '<i class="fa-solid fa-volume-high text-info"></i>';
        }
    },

    // Navigation / Views
    showView(viewName) {
        const views = ['generator-view', 'quiz-view', 'result-view', 'leaderboard-view', 'profile-view', 'admin-view'];
        views.forEach(v => {
            const el = document.getElementById(v);
            if (el) el.style.display = 'none';
        });

        // Update nav links
        document.querySelectorAll('.nav-link').forEach(link => link.classList.remove('active'));
        const activeNav = document.getElementById(`nav-${viewName}`);
        if (activeNav) activeNav.classList.add('active');

        const target = document.getElementById(`${viewName}-view`);
        if (target) {
            target.style.display = 'block';
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        // View specific loaders
        if (viewName === 'leaderboard') this.loadLeaderboard();
        if (viewName === 'profile') this.loadUserProfile();
        if (viewName === 'admin') this.loadAdminQuestions();
    },

    routeFromUrl() {
        const hash = window.location.hash.replace('#', '') || 'generator';
        if (['generator', 'quiz', 'leaderboard', 'profile', 'admin'].includes(hash)) {
            this.showView(hash);
        } else {
            this.showView('generator');
        }
    },

    // Authentication
    async checkAuth() {
        try {
            const res = await fetch('/api/auth/me');
            const data = await res.json();
            if (data.authenticated) {
                this.user = data.user;
                this.renderUserNav(true);
            } else {
                this.user = null;
                this.renderUserNav(false);
            }
        } catch (e) {
            console.error('Auth check error:', e);
        }
    },

    renderUserNav(isLoggedIn) {
        const authContainer = document.getElementById('auth-nav-container');
        const adminLink = document.getElementById('nav-admin-item');

        if (isLoggedIn && this.user) {
            authContainer.innerHTML = `
                <div class="dropdown">
                    <button class="btn btn-outline-light dropdown-toggle btn-sm d-flex align-items-center gap-2" type="button" data-bs-toggle="dropdown">
                        <i class="fa-solid fa-circle-user text-info"></i>
                        <span>${this.user.username}</span>
                        ${this.user.role === 'admin' ? '<span class="badge bg-warning text-dark ms-1">Admin</span>' : ''}
                    </button>
                    <ul class="dropdown-menu dropdown-menu-end shadow">
                        <li><a class="dropdown-item" href="#profile" onclick="App.showView('profile')"><i class="fa-solid fa-chart-line me-2"></i>My Profile</a></li>
                        ${this.user.role === 'admin' ? '<li><a class="dropdown-item" href="#admin" onclick="App.showView(\'admin\')"><i class="fa-solid fa-gear me-2"></i>Admin Panel</a></li>' : ''}
                        <li><hr class="dropdown-divider"></li>
                        <li><a class="dropdown-item text-danger" href="javascript:void(0)" onclick="App.logout()"><i class="fa-solid fa-right-from-bracket me-2"></i>Logout</a></li>
                    </ul>
                </div>
            `;
            if (adminLink) {
                adminLink.style.display = this.user.role === 'admin' ? 'block' : 'none';
            }
        } else {
            authContainer.innerHTML = `
                <button class="btn btn-outline-primary btn-sm px-3 fw-semibold" onclick="App.openAuthModal()">
                    <i class="fa-solid fa-user me-1"></i> Sign In
                </button>
            `;
            if (adminLink) adminLink.style.display = 'none';
        }
    },

    openAuthModal() {
        const modalEl = document.getElementById('authModal');
        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        modal.show();
    },

    async handleLogin(event) {
        event.preventDefault();
        const form = event.target;
        const username = form.username.value;
        const password = form.password.value;
        const alertBox = document.getElementById('login-alert');

        alertBox.classList.add('d-none');
        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });
            const data = await res.json();
            if (res.ok) {
                this.user = data.user;
                this.renderUserNav(true);
                bootstrap.Modal.getInstance(document.getElementById('authModal')).hide();
                form.reset();
            } else {
                alertBox.textContent = data.error || 'Login failed';
                alertBox.classList.remove('d-none');
            }
        } catch (e) {
            alertBox.textContent = 'Network error during login';
            alertBox.classList.remove('d-none');
        }
    },

    async handleRegister(event) {
        event.preventDefault();
        const form = event.target;
        const username = form.reg_username.value;
        const email = form.reg_email.value;
        const password = form.reg_password.value;
        const alertBox = document.getElementById('register-alert');

        alertBox.classList.add('d-none');
        try {
            const res = await fetch('/api/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, email, password })
            });
            const data = await res.json();
            if (res.ok) {
                this.user = data.user;
                this.renderUserNav(true);
                bootstrap.Modal.getInstance(document.getElementById('authModal')).hide();
                form.reset();
            } else {
                alertBox.textContent = data.error || 'Registration failed';
                alertBox.classList.remove('d-none');
            }
        } catch (e) {
            alertBox.textContent = 'Network error during registration';
            alertBox.classList.remove('d-none');
        }
    },

    async logout() {
        await fetch('/api/auth/logout', { method: 'POST' });
        this.user = null;
        this.renderUserNav(false);
        this.showView('generator');
    },

    // -------------------------------------------------------------
    // Quiz Generator Configuration
    // -------------------------------------------------------------
    async loadCategories() {
        const catContainer = document.getElementById('categories-container');
        if (!catContainer) return;

        try {
            const res = await fetch('/api/categories');
            const data = await res.json();
            const categories = data.categories || [];

            let html = `
                <div class="category-pill ${this.selectedCategory === 'All' ? 'selected' : ''}" onclick="App.selectCategory('All', this)">
                    <i class="fa-solid fa-shapes"></i>
                    <span>All GK</span>
                </div>
            `;

            const iconMap = {
                'History': 'fa-landmark',
                'Geography': 'fa-earth-americas',
                'Science': 'fa-flask',
                'Sports': 'fa-trophy',
                'Politics': 'fa-scale-balanced',
                'Current Affairs': 'fa-newspaper',
                'Entertainment': 'fa-film',
                'Technology': 'fa-microchip'
            };

            categories.forEach(c => {
                const icon = iconMap[c.category] || 'fa-lightbulb';
                html += `
                    <div class="category-pill ${this.selectedCategory === c.category ? 'selected' : ''}" onclick="App.selectCategory('${c.category}', this)">
                        <i class="fa-solid ${icon}"></i>
                        <span>${c.category}</span>
                        <small class="text-muted" style="font-size: 0.7rem;">(${c.count})</small>
                    </div>
                `;
            });

            catContainer.innerHTML = html;
        } catch (e) {
            console.error('Failed to load categories:', e);
        }
    },

    selectCategory(cat, el = null) {
        this.selectedCategory = cat;
        document.querySelectorAll('.category-pill').forEach(p => p.classList.remove('selected'));
        const target = el || (window.event ? window.event.currentTarget : null);
        if (target) target.classList.add('selected');
    },

    selectDifficulty(diff, btn = null) {
        this.selectedDifficulty = diff;
        document.querySelectorAll('#difficulty-group .segmented-btn').forEach(b => b.classList.remove('selected'));
        const target = btn || (window.event ? window.event.currentTarget : null);
        if (target) target.classList.add('selected');
    },

    selectNumQuestions(num, btn = null) {
        this.selectedNumQuestions = parseInt(num);
        document.querySelectorAll('#count-group .segmented-btn').forEach(b => b.classList.remove('selected'));
        const target = btn || (window.event ? window.event.currentTarget : null);
        if (target) target.classList.add('selected');
    },

    // -------------------------------------------------------------
    // Active Quiz Lifecycle & Game Loop
    // -------------------------------------------------------------
    async startQuiz() {
        const btn = document.getElementById('btn-start-quiz');
        if (btn) btn.disabled = true;

        try {
            const res = await fetch('/api/quiz/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    category: this.selectedCategory,
                    difficulty: this.selectedDifficulty,
                    num_questions: this.selectedNumQuestions
                })
            });
            const data = await res.json();
            if (res.ok) {
                this.currentAttemptId = data.attempt_id;
                this.showView('quiz');
                this.loadNextQuestion();
            } else {
                alert('Could not start quiz: ' + (data.error || 'Unknown error'));
            }
        } catch (e) {
            alert('Error starting quiz. Please check backend connection.');
        } finally {
            if (btn) btn.disabled = false;
        }
    },

    async loadNextQuestion() {
        // Reset per-question state
        this.currentHintUsed = 'none';
        this.hideFeedback();
        document.getElementById('hint-display-box').style.display = 'none';

        try {
            const res = await fetch(`/api/quiz/${this.currentAttemptId}/current`);
            const data = await res.json();

            if (data.is_finished) {
                this.finishQuiz();
                return;
            }

            this.currentQuestion = data;
            this.renderQuestion(data);
            this.startTimer();
        } catch (e) {
            console.error('Error fetching question:', e);
        }
    },

    renderQuestion(q) {
        // Update HUD
        document.getElementById('hud-category').textContent = q.category;
        document.getElementById('hud-difficulty').textContent = q.difficulty.toUpperCase();
        document.getElementById('hud-counter').textContent = `Question ${q.question_index + 1} of ${q.total_questions}`;
        document.getElementById('hud-score').textContent = q.score;

        // Render Hearts
        this.renderHearts(q.hearts_left);

        // Render Streak
        const streakEl = document.getElementById('hud-streak-container');
        if (q.streak > 1) {
            streakEl.innerHTML = `<span class="streak-badge"><i class="fa-solid fa-fire me-1"></i>${q.streak}x Streak!</span>`;
        } else {
            streakEl.innerHTML = '';
        }

        // Render Lifeline Buttons
        const hint5050Btn = document.getElementById('btn-hint-5050');
        const hintTextBtn = document.getElementById('btn-hint-text');
        const skipBtn = document.getElementById('btn-skip');

        hint5050Btn.disabled = q.hints_5050_left <= 0;
        document.getElementById('count-hint-5050').textContent = q.hints_5050_left;

        hintTextBtn.disabled = q.hints_text_left <= 0;
        document.getElementById('count-hint-text').textContent = q.hints_text_left;

        skipBtn.disabled = q.skips_left <= 0;
        document.getElementById('count-skip').textContent = q.skips_left;

        // Render optional illustration image (Amazon S3)
        const imgContainer = document.getElementById('quiz-question-image-container');
        const imgEl = document.getElementById('quiz-question-image');
        if (imgContainer && imgEl) {
            if (q.image_url) {
                imgEl.src = q.image_url;
                imgContainer.style.display = 'block';
            } else {
                imgContainer.style.display = 'none';
                imgEl.src = '';
            }
        }

        // Question text
        document.getElementById('quiz-question-text').textContent = q.question;

        // Render Options Cards
        const optionsContainer = document.getElementById('quiz-options-container');
        const letters = ['A', 'B', 'C', 'D'];
        let optionsHtml = '';

        q.options.forEach((opt, idx) => {
            optionsHtml += `
                <div class="option-card" id="option-btn-${idx}" onclick="App.submitAnswer('${opt.replace(/'/g, "\\'")}', ${idx})">
                    <div class="option-letter">${letters[idx]}</div>
                    <div class="option-text flex-grow-1">${opt}</div>
                </div>
            `;
        });
        optionsContainer.innerHTML = optionsHtml;
    },

    renderHearts(heartsCount) {
        const container = document.getElementById('hud-hearts');
        let html = '';
        for (let i = 1; i <= 3; i++) {
            if (i <= heartsCount) {
                html += '<i class="fa-solid fa-heart heart-icon"></i>';
            } else {
                html += '<i class="fa-solid fa-heart-crack heart-icon lost"></i>';
            }
        }
        container.innerHTML = html;
    },

    // Timer Implementation
    startTimer() {
        this.stopTimer();
        this.timeRemaining = 30;
        this.timeSpent = 0;
        this.updateTimerBar();

        this.timerInterval = setInterval(() => {
            this.timeRemaining--;
            this.timeSpent++;
            this.updateTimerBar();

            if (this.timeRemaining <= 5 && this.timeRemaining > 0) {
                this.sound.playTick();
            }

            if (this.timeRemaining <= 0) {
                this.stopTimer();
                this.handleTimeout();
            }
        }, 1000);
    },

    stopTimer() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
    },

    updateTimerBar() {
        const bar = document.getElementById('quiz-timer-bar');
        const text = document.getElementById('quiz-timer-seconds');
        const pct = (this.timeRemaining / 30) * 100;

        if (bar) {
            bar.style.width = `${pct}%`;
            bar.classList.remove('warning', 'danger');
            if (this.timeRemaining <= 10 && this.timeRemaining > 5) {
                bar.classList.add('warning');
            } else if (this.timeRemaining <= 5) {
                bar.classList.add('danger');
            }
        }

        if (text) text.textContent = `${this.timeRemaining}s`;
    },

    handleTimeout() {
        this.submitAnswer(null, -1, true);
    },

    // Hint Actions
    async useHint5050() {
        const btn = document.getElementById('btn-hint-5050');
        btn.disabled = true;

        try {
            const res = await fetch(`/api/quiz/${this.currentAttemptId}/hint`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ hint_type: '50-50' })
            });
            const data = await res.json();
            if (res.ok) {
                this.currentHintUsed = this.currentHintUsed === 'text' ? 'both' : '50-50';
                document.getElementById('count-hint-5050').textContent = data.hints_5050_left;

                // Disable the two wrong options visually
                const cards = document.querySelectorAll('.option-card');
                cards.forEach(card => {
                    const text = card.querySelector('.option-text').textContent.trim();
                    if (data.disabled_options.includes(text)) {
                        card.classList.add('disabled-5050');
                    }
                });
            } else {
                alert(data.error);
            }
        } catch (e) {
            console.error('Hint error:', e);
        }
    },

    async useHintText() {
        const btn = document.getElementById('btn-hint-text');
        btn.disabled = true;

        try {
            const res = await fetch(`/api/quiz/${this.currentAttemptId}/hint`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ hint_type: 'text' })
            });
            const data = await res.json();
            if (res.ok) {
                this.currentHintUsed = this.currentHintUsed === '50-50' ? 'both' : 'text';
                document.getElementById('count-hint-text').textContent = data.hints_text_left;

                const hintBox = document.getElementById('hint-display-box');
                hintBox.innerHTML = `<strong><i class="fa-regular fa-lightbulb me-1"></i> Hint:</strong> ${data.hint_text}`;
                hintBox.style.display = 'block';
            } else {
                alert(data.error);
            }
        } catch (e) {
            console.error('Hint error:', e);
        }
    },

    async skipQuestion() {
        this.stopTimer();
        const btn = document.getElementById('btn-skip');
        btn.disabled = true;

        try {
            const res = await fetch(`/api/quiz/${this.currentAttemptId}/skip`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await res.json();
            if (res.ok) {
                document.getElementById('count-skip').textContent = data.skips_left;
                if (data.is_finished) {
                    this.finishQuiz();
                } else {
                    this.loadNextQuestion();
                }
            } else {
                alert(data.error);
            }
        } catch (e) {
            console.error('Skip error:', e);
        }
    },

    // Answer Submission & Instant Feedback
    async submitAnswer(selectedAnswer, selectedIdx, timedOut = false) {
        this.stopTimer();

        // Disable all options immediately to prevent multiple clicks
        document.querySelectorAll('.option-card').forEach(el => el.style.pointerEvents = 'none');

        try {
            const res = await fetch(`/api/quiz/${this.currentAttemptId}/answer`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    selected_answer: selectedAnswer,
                    time_spent: this.timeSpent,
                    timed_out: timedOut,
                    hint_used: this.currentHintUsed
                })
            });
            const data = await res.json();

            if (!res.ok) {
                alert(data.error || 'Submission error');
                return;
            }

            // Audio and Visual highlight
            if (data.is_correct) {
                this.sound.playCorrect();
                if (selectedIdx >= 0) {
                    document.getElementById(`option-btn-${selectedIdx}`).classList.add('correct');
                }
            } else {
                this.sound.playWrong();
                if (selectedIdx >= 0) {
                    document.getElementById(`option-btn-${selectedIdx}`).classList.add('wrong');
                }
                // Reveal the correct option in green
                document.querySelectorAll('.option-card').forEach(card => {
                    const text = card.querySelector('.option-text').textContent.trim();
                    if (text === data.correct_answer) {
                        card.classList.add('correct');
                    }
                });
            }

            // Update hearts and score
            this.renderHearts(data.hearts_left);
            document.getElementById('hud-score').textContent = data.current_score;

            // Show Feedback Overlay
            this.showFeedback(data, timedOut);

        } catch (e) {
            console.error('Answer submission error:', e);
        }
    },

    showFeedback(data, timedOut) {
        const feedbackContainer = document.getElementById('quiz-feedback-box');
        const titleEl = document.getElementById('feedback-title');
        const explanationEl = document.getElementById('feedback-explanation');
        const pointsBadge = document.getElementById('feedback-points-badge');
        const nextBtn = document.getElementById('btn-next-action');

        feedbackContainer.className = `feedback-card ${data.is_correct ? 'correct' : 'wrong'}`;

        if (data.is_correct) {
            titleEl.innerHTML = `<i class="fa-solid fa-circle-check text-success me-2"></i> Correct!`;
            pointsBadge.className = 'badge bg-success';
            pointsBadge.textContent = `+${data.points_awarded} Points`;
        } else if (timedOut) {
            titleEl.innerHTML = `<i class="fa-solid fa-clock text-danger me-2"></i> Time Expired! (-1 Heart)`;
            pointsBadge.className = 'badge bg-danger';
            pointsBadge.textContent = `0 Points`;
        } else {
            titleEl.innerHTML = `<i class="fa-solid fa-circle-xmark text-danger me-2"></i> Incorrect! (-1 Heart)`;
            pointsBadge.className = 'badge bg-danger';
            pointsBadge.textContent = `0 Points`;
        }

        explanationEl.innerHTML = `
            <div class="mb-1"><strong>Correct Answer:</strong> ${data.correct_answer}</div>
            ${data.explanation ? `<div class="small text-muted mt-1"><em>💡 ${data.explanation}</em></div>` : ''}
        `;

        if (data.is_game_over) {
            nextBtn.textContent = 'View Game Over';
            nextBtn.onclick = () => this.showGameOver();
        } else if (data.is_completed) {
            nextBtn.textContent = 'View Final Results';
            nextBtn.onclick = () => this.finishQuiz();
        } else {
            nextBtn.textContent = 'Next Question →';
            nextBtn.onclick = () => this.loadNextQuestion();
        }

        feedbackContainer.style.display = 'block';
    },

    hideFeedback() {
        const feedbackContainer = document.getElementById('quiz-feedback-box');
        if (feedbackContainer) feedbackContainer.style.display = 'none';
    },

    showGameOver() {
        this.sound.playGameOver();
        const modal = new bootstrap.Modal(document.getElementById('gameOverModal'));
        modal.show();
    },

    // -------------------------------------------------------------
    // Results & Exports
    // -------------------------------------------------------------
    async finishQuiz() {
        this.stopTimer();
        this.showView('result');

        try {
            const res = await fetch(`/api/quiz/${this.currentAttemptId}/result`);
            const data = await res.json();
            this.renderResultView(data);
        } catch (e) {
            console.error('Error fetching result:', e);
        }
    },

    renderResultView(data) {
        const att = data.attempt;
        const reviews = data.reviews || [];

        // Sound celebration if passed/good score
        if (att.accuracy >= 60) {
            this.sound.playCelebration();
        }

        // Stats summary
        document.getElementById('res-score').textContent = att.score;
        document.getElementById('res-accuracy').textContent = `${att.accuracy}%`;
        document.getElementById('res-time').textContent = `${att.time_taken_seconds}s`;
        document.getElementById('res-streak').textContent = `${att.max_streak}x`;
        document.getElementById('res-hearts').textContent = `${att.hearts_left} ❤️`;
        document.getElementById('res-hints').textContent = `${att.hints_used}`;

        // Header status
        const statusEl = document.getElementById('res-status-title');
        if (att.status === 'game_over') {
            statusEl.innerHTML = `<span class="text-danger"><i class="fa-solid fa-heart-crack me-2"></i>Game Over (Out of Lives)</span>`;
        } else if (att.accuracy >= 70) {
            statusEl.innerHTML = `<span class="text-success"><i class="fa-solid fa-trophy me-2"></i>Outstanding Quizmaster!</span>`;
        } else {
            statusEl.innerHTML = `<span class="text-info"><i class="fa-solid fa-award me-2"></i>Quiz Completed!</span>`;
        }

        // Export links (Pre-signed S3 URLs or local fallbacks)
        const csvBtn = document.getElementById('btn-export-csv');
        const pdfBtn = document.getElementById('btn-export-pdf');
        if (csvBtn) csvBtn.href = att.csv_url || `/api/attempts/${att.id}/export/csv`;
        if (pdfBtn) pdfBtn.href = att.pdf_url || `/api/attempts/${att.id}/export/pdf`;

        // Question Review Items
        const reviewContainer = document.getElementById('result-review-list');
        let html = '';

        reviews.forEach((r, idx) => {
            const isCorrect = r.is_correct;
            const isSkipped = r.is_skipped;
            const badgeClass = isCorrect ? 'bg-success' : isSkipped ? 'bg-warning text-dark' : 'bg-danger';
            const badgeText = isCorrect ? `Correct (+${r.points_awarded} pts)` : isSkipped ? 'Skipped' : 'Wrong (0 pts)';

            html += `
                <div class="glass-card mb-3 p-3" style="border-left: 5px solid ${isCorrect ? 'var(--success)' : isSkipped ? 'var(--warning)' : 'var(--error)'}">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span class="badge bg-secondary">Q${idx + 1} &bull; ${r.category} (${r.difficulty})</span>
                        <span class="badge ${badgeClass}">${badgeText}</span>
                    </div>
                    <h6 class="fw-bold mb-2">${r.question}</h6>
                    <div class="row small g-2">
                        <div class="col-sm-6">
                            <strong>Your Answer:</strong> 
                            <span class="${isCorrect ? 'text-success fw-bold' : 'text-danger fw-bold'}">
                                ${r.user_answer || 'No Answer'}
                            </span>
                        </div>
                        <div class="col-sm-6">
                            <strong>Correct Answer:</strong> 
                            <span class="text-success fw-bold">${r.correct_answer}</span>
                        </div>
                    </div>
                    ${r.explanation ? `<p class="small text-muted mt-2 mb-0"><em>💡 Explanation: ${r.explanation}</em></p>` : ''}
                </div>
            `;
        });

        reviewContainer.innerHTML = html;
    },

    // -------------------------------------------------------------
    // Leaderboard
    // -------------------------------------------------------------
    async loadLeaderboard() {
        const cat = document.getElementById('leaderboard-category-filter')?.value || 'All';
        const tbody = document.getElementById('leaderboard-tbody');
        if (!tbody) return;

        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-muted"><i class="fa-solid fa-spinner fa-spin me-2"></i>Loading leaderboard...</td></tr>';

        try {
            const res = await fetch(`/api/leaderboard?category=${encodeURIComponent(cat)}`);
            const data = await res.json();
            const leaders = data.leaderboard || [];

            if (leaders.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-muted">No completed quiz scores yet in this category. Be the first!</td></tr>';
                return;
            }

            let html = '';
            leaders.forEach(row => {
                let rankBadge = `<span class="rank-badge rank-other">${row.rank}</span>`;
                if (row.rank === 1) rankBadge = `<span class="rank-badge rank-1">🥇 1</span>`;
                if (row.rank === 2) rankBadge = `<span class="rank-badge rank-2">🥈 2</span>`;
                if (row.rank === 3) rankBadge = `<span class="rank-badge rank-3">🥉 3</span>`;

                html += `
                    <tr>
                        <td style="width: 60px;">${rankBadge}</td>
                        <td class="fw-bold"><i class="fa-solid fa-user-circle me-1 text-primary"></i> ${row.username}</td>
                        <td class="fw-bold text-primary">${row.score}</td>
                        <td>${row.accuracy}%</td>
                        <td><span class="badge bg-light text-dark border">${row.category}</span></td>
                        <td><span class="badge bg-secondary text-capitalize">${row.difficulty}</span></td>
                        <td class="small text-muted">${row.date}</td>
                    </tr>
                `;
            });
            tbody.innerHTML = html;
        } catch (e) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-danger py-4">Failed to load leaderboard data</td></tr>';
        }
    },

    // -------------------------------------------------------------
    // User Profile
    // -------------------------------------------------------------
    async loadUserProfile() {
        if (!this.user) {
            this.openAuthModal();
            return;
        }

        document.getElementById('profile-username').textContent = this.user.username;
        document.getElementById('profile-email').textContent = this.user.email;
        document.getElementById('profile-role').textContent = this.user.role.toUpperCase();

        // Update SNS Subscription state
        const snsBadge = document.getElementById('sns-badge-status');
        const snsBtn = document.getElementById('btn-subscribe-sns');
        const snsAlert = document.getElementById('sns-subscribe-alert');
        if (snsAlert) snsAlert.classList.add('d-none');

        if (this.user.sns_subscribed) {
            if (snsBadge) {
                snsBadge.className = 'badge bg-success';
                snsBadge.textContent = 'Subscribed';
            }
            if (snsBtn) {
                snsBtn.disabled = true;
                snsBtn.className = 'btn btn-outline-success btn-sm w-100 fw-semibold';
                snsBtn.innerHTML = '<i class="fa-solid fa-circle-check me-1"></i> Subscribed to SNS Alerts';
            }
        } else {
            if (snsBadge) {
                snsBadge.className = 'badge bg-secondary';
                snsBadge.textContent = 'Not Subscribed';
            }
            if (snsBtn) {
                snsBtn.disabled = false;
                snsBtn.className = 'btn btn-outline-warning btn-sm w-100 fw-semibold';
                snsBtn.innerHTML = '<i class="fa-solid fa-envelope-circle-check me-1"></i> Subscribe for Score Emails';
            }
        }

        const historyTbody = document.getElementById('history-tbody');
        try {
            const res = await fetch('/api/user/history');
            const data = await res.json();
            const stats = data.stats || {};
            const history = data.history || [];

            document.getElementById('user-stat-quizzes').textContent = stats.total_attempts || 0;
            document.getElementById('user-stat-high-score').textContent = stats.high_score || 0;
            document.getElementById('user-stat-avg-acc').textContent = `${stats.avg_accuracy || 0}%`;

            if (history.length === 0) {
                historyTbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">No quiz history found. Play your first quiz!</td></tr>';
                return;
            }

            let html = '';
            history.forEach(h => {
                html += `
                    <tr>
                        <td class="small text-muted">${h.date}</td>
                        <td><span class="badge bg-light text-dark border">${h.category}</span></td>
                        <td class="text-capitalize">${h.difficulty}</td>
                        <td class="fw-bold text-primary">${h.score}</td>
                        <td>${h.accuracy}%</td>
                        <td>
                            <span class="badge bg-${h.status === 'completed' ? 'success' : 'danger'}">${h.status}</span>
                        </td>
                    </tr>
                `;
            });
            historyTbody.innerHTML = html;
        } catch (e) {
            console.error('History load error:', e);
        }
    },

    async subscribeSns() {
        if (!this.user) {
            this.openAuthModal();
            return;
        }

        const btn = document.getElementById('btn-subscribe-sns');
        const alertBox = document.getElementById('sns-subscribe-alert');
        if (btn) btn.disabled = true;

        try {
            const res = await fetch('/api/user/subscribe-sns', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: this.user.email })
            });
            const data = await res.json();
            if (res.ok && data.success) {
                this.user.sns_subscribed = 1;
                const badge = document.getElementById('sns-badge-status');
                if (badge) {
                    badge.className = 'badge bg-success';
                    badge.textContent = 'Subscribed';
                }
                if (alertBox) {
                    alertBox.className = 'small mt-2 alert alert-success py-1 px-2';
                    alertBox.textContent = data.message || 'Subscription requested! Please check your email inbox to confirm.';
                    alertBox.classList.remove('d-none');
                }
                if (btn) {
                    btn.className = 'btn btn-outline-success btn-sm w-100 fw-semibold';
                    btn.innerHTML = '<i class="fa-solid fa-circle-check me-1"></i> Subscribed to SNS Alerts';
                }
            } else {
                if (alertBox) {
                    alertBox.className = 'small mt-2 alert alert-danger py-1 px-2';
                    alertBox.textContent = data.error || data.message || 'Subscription failed';
                    alertBox.classList.remove('d-none');
                }
                if (btn) btn.disabled = false;
            }
        } catch (e) {
            if (alertBox) {
                alertBox.className = 'small mt-2 alert alert-danger py-1 px-2';
                alertBox.textContent = 'Network error subscribing to SNS';
                alertBox.classList.remove('d-none');
            }
            if (btn) btn.disabled = false;
        }
    },

    // -------------------------------------------------------------
    // Admin Question Management (CRUD)
    // -------------------------------------------------------------
    async loadAdminQuestions() {
        const cat = document.getElementById('admin-category-filter')?.value || 'All';
        const search = document.getElementById('admin-search-input')?.value || '';
        const tbody = document.getElementById('admin-questions-tbody');

        tbody.innerHTML = '<tr><td colspan="6" class="text-center py-4"><i class="fa-solid fa-spinner fa-spin me-2"></i>Loading questions...</td></tr>';

        try {
            const res = await fetch(`/api/admin/questions?category=${encodeURIComponent(cat)}&search=${encodeURIComponent(search)}`);
            const data = await res.json();
            const questions = data.questions || [];
            this.adminQuestions = questions;

            document.getElementById('admin-total-questions-badge').textContent = `${questions.length} Questions`;

            if (questions.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-muted">No questions found matching criteria</td></tr>';
                return;
            }

            let html = '';
            questions.forEach(q => {
                html += `
                    <tr>
                        <td class="fw-semibold">#${q.id}</td>
                        <td><span class="badge bg-info text-dark">${q.category}</span></td>
                        <td><span class="badge bg-secondary text-capitalize">${q.difficulty}</span></td>
                        <td class="fw-medium">${q.question}</td>
                        <td class="small text-success fw-bold">${q.correct_answer}</td>
                        <td>
                            <div class="btn-group btn-group-sm">
                                <button class="btn btn-outline-primary" onclick="App.openEditQuestionModal(${q.id})">
                                    <i class="fa-solid fa-pen"></i>
                                </button>
                                <button class="btn btn-outline-danger" onclick="App.deleteQuestion(${q.id})">
                                    <i class="fa-solid fa-trash"></i>
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            });
            tbody.innerHTML = html;
        } catch (e) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-danger py-4">Error loading questions. Admin rights required.</td></tr>';
        }
    },

    openAddQuestionModal() {
        const form = document.getElementById('questionForm');
        form.reset();
        document.getElementById('question-modal-title').textContent = 'Add New Question';
        document.getElementById('edit-q-id').value = '';
        const keyInput = document.getElementById('q-image-s3-key');
        if (keyInput) keyInput.value = '';
        const preview = document.getElementById('q-image-preview');
        if (preview) preview.innerHTML = '';
        const fileInput = document.getElementById('q-image-file');
        if (fileInput) fileInput.value = '';

        const modal = new bootstrap.Modal(document.getElementById('questionModal'));
        modal.show();
    },

    openEditQuestionModal(qId) {
        const q = (this.adminQuestions || []).find(item => item.id === qId);
        if (!q) return;
        document.getElementById('question-modal-title').textContent = 'Edit Question #' + q.id;
        document.getElementById('edit-q-id').value = q.id;
        document.getElementById('q-category').value = q.category;
        document.getElementById('q-difficulty').value = q.difficulty;
        document.getElementById('q-question').value = q.question;
        document.getElementById('q-option-a').value = q.option_a;
        document.getElementById('q-option-b').value = q.option_b;
        document.getElementById('q-option-c').value = q.option_c;
        document.getElementById('q-option-d').value = q.option_d;
        document.getElementById('q-correct-answer').value = q.correct_answer;
        document.getElementById('q-hint').value = q.hint || '';
        document.getElementById('q-explanation').value = q.explanation || '';

        const keyInput = document.getElementById('q-image-s3-key');
        if (keyInput) keyInput.value = q.image_s3_key || '';

        const preview = document.getElementById('q-image-preview');
        if (preview) {
            if (q.image_s3_key) {
                preview.innerHTML = `
                    <div class="mt-2 text-info">
                        <i class="fa-brands fa-aws me-1"></i> Current Image: <code>${q.image_s3_key}</code>
                        ${q.image_url ? `<div class="mt-1"><img src="${q.image_url}" alt="Preview" style="max-height: 80px;" class="rounded border"></div>` : ''}
                    </div>
                `;
            } else {
                preview.innerHTML = '';
            }
        }
        const fileInput = document.getElementById('q-image-file');
        if (fileInput) fileInput.value = '';

        const modal = new bootstrap.Modal(document.getElementById('questionModal'));
        modal.show();
    },

    async handleImageUpload(event) {
        const file = event.target.files[0];
        if (!file) return;

        const preview = document.getElementById('q-image-preview');
        const keyInput = document.getElementById('q-image-s3-key');
        if (preview) {
            preview.innerHTML = '<i class="fa-solid fa-spinner fa-spin me-1"></i> Uploading to Amazon S3...';
        }

        const formData = new FormData();
        formData.append('image', file);

        try {
            const res = await fetch('/api/admin/questions/upload-image', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (res.ok && data.image_s3_key) {
                if (keyInput) keyInput.value = data.image_s3_key;
                if (preview) {
                    preview.innerHTML = `
                        <div class="mt-2 text-success">
                            <i class="fa-solid fa-circle-check me-1"></i> Uploaded to S3: <code>${data.image_s3_key}</code>
                            <div class="mt-1"><img src="${data.image_url}" alt="Preview" style="max-height: 80px;" class="rounded border shadow-sm"></div>
                        </div>
                    `;
                }
            } else {
                if (preview) {
                    preview.innerHTML = `<span class="text-danger"><i class="fa-solid fa-triangle-exclamation me-1"></i> ${data.error || 'Upload failed'}</span>`;
                }
            }
        } catch (e) {
            if (preview) {
                preview.innerHTML = '<span class="text-danger"><i class="fa-solid fa-triangle-exclamation me-1"></i> Network error uploading image</span>';
            }
        }
    },

    async handleQuestionSubmit(event) {
        event.preventDefault();
        const form = event.target;
        const qId = document.getElementById('edit-q-id').value;
        const isEdit = Boolean(qId);

        const payload = {
            category: form.category.value,
            difficulty: form.difficulty.value,
            question: form.question.value,
            option_a: form.option_a.value,
            option_b: form.option_b.value,
            option_c: form.option_c.value,
            option_d: form.option_d.value,
            correct_answer: form.correct_answer.value,
            hint: form.hint.value,
            explanation: form.explanation.value,
            image_s3_key: document.getElementById('q-image-s3-key')?.value || null
        };

        const url = isEdit ? `/api/admin/questions/${qId}` : '/api/admin/questions';
        const method = isEdit ? 'PUT' : 'POST';

        try {
            const res = await fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (res.ok) {
                bootstrap.Modal.getInstance(document.getElementById('questionModal')).hide();
                this.loadAdminQuestions();
                this.loadCategories(); // update counts
            } else {
                alert(data.error || 'Failed to save question');
            }
        } catch (e) {
            alert('Error submitting question');
        }
    },

    async deleteQuestion(id) {
        if (!confirm(`Are you sure you want to delete question #${id}?`)) return;

        try {
            const res = await fetch(`/api/admin/questions/${id}`, { method: 'DELETE' });
            if (res.ok) {
                this.loadAdminQuestions();
                this.loadCategories();
            } else {
                const data = await res.json();
                alert(data.error || 'Delete failed');
            }
        } catch (e) {
            alert('Error deleting question');
        }
    },

    // Global Listeners
    setupEventListeners() {
        window.addEventListener('hashchange', () => this.routeFromUrl());
    }
};

// Initialize App on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
    App.init();
});
