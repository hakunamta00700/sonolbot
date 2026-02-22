from playwright.sync_api import sync_playwright
import os
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)  # Open visible browser for login
    page = browser.new_page()

    print("브라우저를 열었습니다. 로그인해주세요...")
    page.goto('https://x.com/karpathy/status/2004607146781278521')

    # Wait for user to login and view the tweet
    print("\n로그인 후 트윗과 답변들을 모두 확인하세요.")
    print("확인이 완료되면 이 창에서 Enter를 눌러주세요...")
    input()

    # Wait for content to load
    page.wait_for_load_state('networkidle')
    time.sleep(2)  # Additional wait for dynamic content

    # Take full page screenshot
    output_image = os.path.join(os.getcwd(), 'tweet_full.png')
    page.screenshot(path=output_image, full_page=True)
    print(f"스크린샷을 저장했습니다: {output_image}")

    # Extract page content
    content = page.content()
    output_html = os.path.join(os.getcwd(), 'tweet_content.html')
    with open(output_html, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"페이지 내용을 저장했습니다: {output_html}")

    # Extract tweet text content
    try:
        # Get main tweet
        main_tweet = page.locator('article[data-testid="tweet"]').first
        tweet_text = main_tweet.locator('[data-testid="tweetText"]').inner_text()
        print("\n=== 원본 트윗 ===")
        print(tweet_text)

        # Get replies
        print("\n=== 답변들 ===")
        replies = page.locator('article[data-testid="tweet"]').all()
        for i, reply in enumerate(replies[1:], 1):  # Skip first (main tweet)
            try:
                reply_text = reply.locator('[data-testid="tweetText"]').inner_text()
                author = reply.locator('[data-testid="User-Name"]').inner_text()
                print(f"\n답변 {i}:")
                print(f"작성자: {author}")
                print(f"내용: {reply_text}")
            except:
                continue

    except Exception as e:
        print(f"텍스트 추출 중 오류: {e}")

    print("\n모든 작업이 완료되었습니다. 브라우저를 닫으려면 Enter를 눌러주세요...")
    input()
    browser.close()
