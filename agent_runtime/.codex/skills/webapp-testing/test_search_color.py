from playwright.sync_api import sync_playwright
import time
import os

save_dir = r"E:\CLAUDE_PROJECT\district\아파트패키지"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    print("브라우저를 열고 있습니다...")
    page.goto('https://jwdtm.com')
    page.wait_for_load_state('networkidle')

    print("\n로그인을 완료해주세요. 30초 후 자동으로 진행됩니다...\n")
    time.sleep(30)

    print("구역카드 패키지 페이지로 이동합니다...")
    try:
        page.goto('https://jwdtm.com/adm/cardpackage', timeout=10000)
    except:
        print(f"리다이렉트 발생, 현재 URL: {page.url}")
        if 'cardpackage' not in page.url:
            time.sleep(2)
            page.goto('https://jwdtm.com/adm/cardpackage', wait_until='domcontentloaded')

    page.wait_for_load_state('networkidle')
    time.sleep(2)

    # 001, 002, 003만 테스트
    for num in [1, 2, 3]:
        district_num = f"{num:03d}"
        print(f"\n{'='*60}")
        print(f"{district_num}번 테스트")
        print(f"{'='*60}")

        # 검색 입력란 초기화
        search_input = page.locator('#sear_package_name')
        search_input.fill('')
        time.sleep(0.3)
        search_input.fill(district_num)
        time.sleep(0.5)

        # 검색 버튼 클릭
        search_button = page.locator('button:has-text("검색")').first
        search_button.click()
        time.sleep(2)
        page.wait_for_load_state('networkidle')

        # 스크린샷
        screenshot_path = os.path.join(save_dir, f"test_{district_num}_search.png")
        page.screenshot(path=screenshot_path, full_page=True)
        print(f"스크린샷: {screenshot_path}")

        # 검색 결과 분석
        rows = page.locator('table tbody tr').all()
        print(f"총 {len(rows)}개 행")

        found_exact = False
        for i, row in enumerate(rows[:10]):  # 처음 10개만
            try:
                first_td = row.locator('td').first
                td_text = first_td.text_content().strip()
                color = first_td.evaluate('el => window.getComputedStyle(el).color')

                if td_text == district_num:
                    print(f"\n★ 정확히 일치하는 행 발견!")
                    print(f"  행 {i}: 텍스트='{td_text}', 색상={color}")

                    # 모든 td 출력
                    all_tds = row.locator('td').all()
                    td_texts = [td.text_content().strip() for td in all_tds]
                    print(f"  전체 셀: {td_texts}")
                    found_exact = True
                    break
            except Exception as e:
                print(f"행 {i} 처리 중 오류: {e}")

        if not found_exact:
            print(f"\n✗ {district_num}번 정확히 일치하는 행을 찾지 못함")
            # 처음 3개 행만 출력
            print("\n처음 3개 행:")
            for i, row in enumerate(rows[:3]):
                try:
                    first_td = row.locator('td').first
                    td_text = first_td.text_content().strip()
                    color = first_td.evaluate('el => window.getComputedStyle(el).color')
                    print(f"  행 {i}: 텍스트='{td_text}', 색상={color}")
                except:
                    pass

        time.sleep(2)

    print("\n30초 후 브라우저를 종료합니다...")
    time.sleep(30)
    browser.close()
