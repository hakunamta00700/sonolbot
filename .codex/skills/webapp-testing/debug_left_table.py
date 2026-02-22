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

    # 페이지 구조 파악
    print("\n=== 페이지 구조 분석 ===")

    # 검색 입력란 확인
    search_input = page.locator('#sear_package_name')
    print(f"검색 입력란: {search_input.count()}개")

    # 모든 테이블 확인
    all_tables = page.locator('table').all()
    print(f"\n총 {len(all_tables)}개의 테이블")

    for idx, table in enumerate(all_tables):
        try:
            print(f"\n[테이블 {idx}]")

            # 테이블의 클래스나 ID 확인
            table_id = table.get_attribute('id')
            table_class = table.get_attribute('class')
            print(f"  ID: {table_id}")
            print(f"  Class: {table_class}")

            # 헤더 확인
            headers = table.locator('thead th, thead td').all()
            header_texts = [h.text_content().strip() for h in headers]
            print(f"  헤더: {header_texts}")

            # tbody tr 개수
            tbody_rows = table.locator('tbody tr').all()
            print(f"  tbody tr: {len(tbody_rows)}개")

        except Exception as e:
            print(f"  오류: {e}")

    # 001번 검색
    district_num = '001'
    print(f"\n\n{district_num}번 검색 중...")

    search_input.fill('')
    time.sleep(0.2)
    search_input.fill(district_num)
    time.sleep(0.3)

    search_button = page.locator('button:has-text("검색")').first
    search_button.click()
    time.sleep(1.5)
    page.wait_for_load_state('networkidle')
    time.sleep(0.5)

    # 검색 후 스크린샷
    screenshot_path = os.path.join(save_dir, f"debug_search_{district_num}.png")
    page.screenshot(path=screenshot_path, full_page=True)
    print(f"검색 후 스크린샷: {screenshot_path}")

    # 검색 후 모든 테이블 다시 확인
    print(f"\n\n=== 검색 후 테이블 분석 ===")
    all_tables = page.locator('table').all()
    print(f"총 {len(all_tables)}개의 테이블")

    for idx, table in enumerate(all_tables):
        try:
            print(f"\n[테이블 {idx}]")

            table_id = table.get_attribute('id')
            table_class = table.get_attribute('class')
            print(f"  ID: {table_id}")
            print(f"  Class: {table_class}")

            headers = table.locator('thead th, thead td').all()
            header_texts = [h.text_content().strip() for h in headers]
            print(f"  헤더: {header_texts}")

            tbody_rows = table.locator('tbody tr').all()
            print(f"  tbody tr: {len(tbody_rows)}개")

            # 처음 3개 행 내용
            for i in range(min(3, len(tbody_rows))):
                try:
                    row = tbody_rows[i]
                    first_td = row.locator('td').first
                    td_text = first_td.text_content().strip()
                    print(f"    행[{i}] 첫 td: '{td_text}'")
                except:
                    pass

        except Exception as e:
            print(f"  오류: {e}")

    print("\n60초 후 브라우저를 종료합니다...")
    time.sleep(60)
    browser.close()
