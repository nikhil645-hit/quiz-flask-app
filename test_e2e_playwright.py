import os
import time
from playwright.sync_api import sync_playwright

def run_e2e_test():
    screenshot_dir = os.path.join(os.path.dirname(__file__), 'screenshot')
    os.makedirs(screenshot_dir, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1400, 'height': 900})
        page = context.new_page()

        print("1. Navigating to http://127.0.0.1:5000...")
        page.goto('http://127.0.0.1:5000', wait_until='networkidle')
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(screenshot_dir, 'Screen_001_Home.png'))
        print("  Saved Screen_001_Home.png")

        print("2. Testing Theme Toggle (Dark/Light)...")
        theme_btn = page.locator('#theme-toggle-btn')
        theme_btn.click()
        page.wait_for_timeout(500)
        curr_theme = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
        print(f"  Theme toggled to: {curr_theme}")
        # Toggle back to dark
        theme_btn.click()
        page.wait_for_timeout(500)

        print("3. Testing Sign In modal...")
        page.locator('#auth-nav-container button').click()
        page.wait_for_selector('#authModal.show')
        page.fill('input[name="username"]', 'admin')
        page.fill('input[name="password"]', 'admin123')
        page.locator('#login-tab button[type="submit"]').click()
        page.wait_for_selector('#nav-admin-item:visible', timeout=5000)
        print("  Admin successfully logged in!")

        print("4. Testing Admin Question Management...")
        page.locator('#nav-admin').click()
        page.wait_for_selector('#admin-view:visible')
        page.wait_for_selector('#admin-questions-tbody tr td:not([colspan])', timeout=5000)
        q_count = page.locator('#admin-questions-tbody tr').count()
        print(f"  Admin questions table loaded with {q_count} questions.")
        page.screenshot(path=os.path.join(screenshot_dir, 'Screen_006_Admin.png'))
        print("  Saved Screen_006_Admin.png")

        print("5. Testing Leaderboard...")
        page.locator('#nav-leaderboard').click()
        page.wait_for_selector('#leaderboard-view:visible')
        page.wait_for_selector('#leaderboard-tbody tr td:not([colspan])', timeout=5000)
        leaders_count = page.locator('#leaderboard-tbody tr').count()
        print(f"  Leaderboard loaded with {leaders_count} top scores.")
        page.screenshot(path=os.path.join(screenshot_dir, 'Screen_005_Leaderboard.png'))
        print("  Saved Screen_005_Leaderboard.png")

        print("6. Returning to Quiz Generator...")
        page.locator('#nav-generator').click()
        page.wait_for_selector('#generator-view:visible')

        print("7. Selecting Category 'Science' & 5 Questions...")
        science_pill = page.locator('.category-pill:has-text("Science")')
        science_pill.click()
        page.wait_for_timeout(300)

        five_q_btn = page.get_by_role("button", name="5 Questions", exact=True)
        five_q_btn.click()
        page.wait_for_timeout(300)

        print("8. Launching Quiz Arena...")
        start_btn = page.locator('#btn-start-quiz')
        start_btn.scroll_into_view_if_needed()
        start_btn.click()

        page.wait_for_selector('#quiz-view:visible', timeout=5000)
        page.wait_for_selector('#quiz-options-container .option-card', timeout=5000)
        print("  Quiz Arena successfully launched!")
        page.screenshot(path=os.path.join(screenshot_dir, 'Screen_002_QuizArena.png'))
        print("  Saved Screen_002_QuizArena.png")

        print("9. Testing 50:50 Lifeline...")
        page.locator('#btn-hint-5050').click()
        page.wait_for_timeout(500)
        disabled_count = page.locator('.option-card.disabled-5050').count()
        print(f"  50:50 hint disabled {disabled_count} wrong options.")

        print("10. Testing Text Hint Lifeline...")
        page.locator('#btn-hint-text').click()
        page.wait_for_selector('#hint-display-box:visible')
        hint_text = page.locator('#hint-display-box').inner_text()
        print(f"  Hint displayed: {hint_text}")

        print("11. Submitting Answer for Question 1...")
        active_opt = page.locator('.option-card:not(.disabled-5050)').first
        active_opt.click()

        page.wait_for_selector('#quiz-feedback-box:visible', timeout=5000)
        feedback_title = page.locator('#feedback-title').inner_text()
        print(f"  Instant Feedback received: {feedback_title}")
        page.screenshot(path=os.path.join(screenshot_dir, 'Screen_003_Feedback.png'))
        print("  Saved Screen_003_Feedback.png")

        print("12. Advancing to Question 2...")
        page.locator('#btn-next-action').click()
        page.wait_for_timeout(600)

        print("13. Testing Skip Lifeline on Question 2...")
        page.locator('#btn-skip').click()
        page.wait_for_timeout(800)
        print("  Question 2 skipped successfully!")

        print("14. Answering remaining questions...")
        for q_num in range(3, 6):
            if page.locator('#result-view:visible').count() > 0:
                break
            if page.locator('#gameOverModal.show').count() > 0:
                print("  Game Over modal detected! Clicking View Result Summary...")
                page.locator('#gameOverModal button:has-text("View Result Summary")').click()
                break

            page.wait_for_selector('#quiz-options-container .option-card', timeout=5000)
            page.wait_for_timeout(400)
            opt = page.locator('.option-card').first
            opt.click()
            page.wait_for_selector('#quiz-feedback-box:visible', timeout=5000)
            page.locator('#btn-next-action').click()
            page.wait_for_timeout(600)

            if page.locator('#gameOverModal.show').count() > 0:
                print("  Game Over modal detected! Clicking View Result Summary...")
                page.locator('#gameOverModal button:has-text("View Result Summary")').click()
                break

        print("15. Verifying Results Screen...")
        page.wait_for_selector('#result-view:visible', timeout=7000)
        page.wait_for_selector('#result-review-list .glass-card', timeout=5000)
        score = page.locator('#res-score').inner_text()
        accuracy = page.locator('#res-accuracy').inner_text()
        reviews = page.locator('#result-review-list .glass-card').count()
        print(f"  Final Score: {score}, Accuracy: {accuracy}, Reviewed Questions: {reviews}")
        page.screenshot(path=os.path.join(screenshot_dir, 'Screen_004_Result.png'))
        print("  Saved Screen_004_Result.png")

        print("16. Verifying Export buttons...")
        csv_href = page.locator('#btn-export-csv').get_attribute('href')
        pdf_href = page.locator('#btn-export-pdf').get_attribute('href')
        print(f"  CSV export link: {csv_href}")
        print(f"  PDF export link: {pdf_href}")
        assert ('/export/csv' in csv_href or 'csv' in csv_href)
        assert ('/export/pdf' in pdf_href or 'pdf' in pdf_href or 'html' in pdf_href)

        print("17. Testing Profile & SNS Subscription UI...")
        page.locator('#auth-nav-container button').click()
        page.locator('a:has-text("My Profile")').click()
        page.wait_for_selector('#profile-view:visible')
        page.wait_for_selector('#btn-subscribe-sns:visible')
        page.locator('#btn-subscribe-sns').click()
        page.wait_for_timeout(1000)
        sns_badge = page.locator('#sns-badge-status').inner_text()
        print(f"  SNS status after subscription click: {sns_badge}")
        page.screenshot(path=os.path.join(screenshot_dir, 'Screen_008_Profile.png'))
        print("  Saved Screen_008_Profile.png")

        print("18. Testing /health endpoint...")
        health_res = page.request.get('http://127.0.0.1:5000/health')
        assert health_res.status == 200
        health_json = health_res.json()
        print(f"  Health Check Response: {health_json}")
        assert health_json.get('status') in ['ok', 'healthy']

        print("19. Testing /aws-status Dashboard...")
        page.goto('http://127.0.0.1:5000/aws-status', wait_until='networkidle')
        page.wait_for_selector('.aws-card', timeout=5000)
        cards_count = page.locator('.aws-card').count()
        print(f"  AWS Status Page loaded with {cards_count} service cards.")
        assert cards_count == 4
        page.screenshot(path=os.path.join(screenshot_dir, 'Screen_007_AWSStatus.png'))
        print("  Saved Screen_007_AWSStatus.png")

        browser.close()
        print("\nALL END-TO-END PLAYWRIGHT & AWS TESTS PASSED 100% SUCCESSFULLY!")

if __name__ == '__main__':
    run_e2e_test()

