from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto('https://jwdtm.com')
    page.wait_for_load_state('networkidle')

    print("브라우저가 열렸습니다. 로그인을 완료해주세요...")
    print("브라우저를 10분 동안 열어둡니다. 로그인 후 다시 요청해주세요.")

    # 10분 동안 대기
    time.sleep(600)

    browser.close()
