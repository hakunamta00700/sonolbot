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

    # 001번만 테스트
    district_num = '001'
    print(f"\n{district_num}번 검색 중...")

    search_input = page.locator('#sear_package_name')
    search_input.fill('')
    time.sleep(0.2)
    search_input.fill(district_num)
    time.sleep(0.3)

    search_button = page.locator('button:has-text("검색")').first
    search_button.click()
    time.sleep(1.5)
    page.wait_for_load_state('networkidle')
    time.sleep(0.5)

    # 검색 결과에서 001번 찾기
    rows = page.locator('table tbody tr').all()
    found = False

    for row in rows:
        try:
            first_td = row.locator('td').first
            td_text = first_td.text_content().strip()

            if td_text == district_num:
                color = first_td.evaluate('el => window.getComputedStyle(el).color')

                if 'rgb(0, 0, 0)' in color or 'rgb(51, 51, 51)' in color:
                    print(f"✓ {district_num}번 발견, 클릭합니다...")
                    row.scroll_into_view_if_needed()
                    time.sleep(0.3)
                    row.click()
                    found = True
                    break
        except:
            continue

    if not found:
        print(f"✗ {district_num}번을 찾지 못했습니다.")
        browser.close()
        exit()

    # 클릭 후 대기
    print("클릭 후 대기 중 (5초)...")
    time.sleep(2)
    page.wait_for_load_state('networkidle')
    time.sleep(3)

    # 스크린샷
    screenshot_path = os.path.join(save_dir, f"debug_{district_num}_after_click.png")
    page.screenshot(path=screenshot_path, full_page=True)
    print(f"스크린샷 저장: {screenshot_path}")

    # 전체 HTML 저장
    html_content = page.content()
    html_path = os.path.join(save_dir, f"debug_{district_num}_full.html")
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"전체 HTML 저장: {html_path}")

    # 모든 테이블 분석
    print("\n=== 모든 테이블 분석 ===")
    tables = page.locator('table').all()
    print(f"총 {len(tables)}개의 테이블")

    for idx, table in enumerate(tables):
        try:
            print(f"\n[테이블 {idx}]")

            # 헤더
            headers = table.locator('thead th, thead td').all()
            header_texts = [h.text_content().strip() for h in headers]
            print(f"  헤더: {header_texts}")

            # tbody tr 개수
            tbody_rows = table.locator('tbody tr').all()
            print(f"  tbody tr: {len(tbody_rows)}개")

            # td 개수
            all_tds = table.locator('td').all()
            print(f"  전체 td: {len(all_tds)}개")

            # 처음 5개 td 내용
            for i in range(min(5, len(all_tds))):
                try:
                    td_text = all_tds[i].text_content().strip()
                    print(f"    td[{i}]: '{td_text}'")
                except:
                    pass

            # 테이블 HTML 일부 저장
            table_html = table.evaluate('el => el.outerHTML')
            table_html_path = os.path.join(save_dir, f"debug_{district_num}_table_{idx}.html")
            with open(table_html_path, 'w', encoding='utf-8') as f:
                f.write(table_html)
            print(f"  테이블 HTML 저장: {table_html_path}")

        except Exception as e:
            print(f"  오류: {e}")

    # 60초 대기 (HTML 파일 확인 시간)
    print("\n60초 후 브라우저를 종료합니다...")
    print("HTML 파일을 확인해주세요.")
    time.sleep(60)
    browser.close()
