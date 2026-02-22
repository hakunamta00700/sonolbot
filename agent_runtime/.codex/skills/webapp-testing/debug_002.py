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
    page.goto('https://jwdtm.com/adm/cardpackage')
    page.wait_for_load_state('networkidle')
    time.sleep(2)

    print("002번 검색 중...")
    search_input = page.locator('#sear_package_name')
    search_input.fill('002')
    time.sleep(0.5)

    search_button = page.locator('button:has-text("검색")').first
    search_button.click()
    time.sleep(2)
    page.wait_for_load_state('networkidle')

    print("002번 패키지 찾는 중...")
    rows = page.locator('table tbody tr').all()

    for row in rows:
        try:
            first_td = row.locator('td').first
            td_text = first_td.text_content().strip()

            if td_text == '002':
                print(f"002번 패키지 발견, 클릭합니다...")
                row.scroll_into_view_if_needed()
                time.sleep(0.5)
                row.click()
                break
        except:
            continue

    print("클릭 후 대기 중 (10초)...")
    time.sleep(5)
    page.wait_for_load_state('networkidle')
    time.sleep(5)

    # HTML 저장
    print("HTML 저장 중...")
    html_content = page.content()
    html_path = os.path.join(save_dir, "002_after_click.html")
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"저장 완료: {html_path}")

    # 스크린샷
    screenshot_path = os.path.join(save_dir, "002_after_click.png")
    page.screenshot(path=screenshot_path, full_page=True)
    print(f"스크린샷 저장: {screenshot_path}")

    # 테이블 구조 분석
    print("\n=== 테이블 구조 분석 ===")
    tables = page.locator('table').all()
    print(f"총 {len(tables)}개의 테이블 발견")

    for idx, table in enumerate(tables):
        try:
            headers = table.locator('thead th, thead td').all()
            header_texts = [h.text_content().strip() for h in headers]

            if '구역번호' in header_texts and '구역명칭' in header_texts:
                print(f"\n[테이블 {idx}] 등록된 구역 리스트 테이블!")
                print(f"헤더: {header_texts}")

                # tbody 확인
                tbody = table.locator('tbody')
                tbody_html = tbody.inner_html()
                print(f"\ntbody HTML (처음 500자):\n{tbody_html[:500]}")

                # tr 확인
                tbody_rows = table.locator('tbody tr').all()
                print(f"\ntbody tr 개수: {len(tbody_rows)}")

                # tr 대신 모든 td 확인
                all_tds = table.locator('td').all()
                print(f"전체 td 개수: {len(all_tds)}")

                # 구역번호로 보이는 텍스트 찾기
                district_numbers = page.locator('text=/^\\d{4}$/').all()
                print(f"\n4자리 숫자 요소 개수: {len(district_numbers)}")
                for i, elem in enumerate(district_numbers[:10]):
                    try:
                        text = elem.text_content().strip()
                        print(f"  [{i}] {text}")
                    except:
                        pass

                break
        except Exception as e:
            print(f"테이블 {idx} 분석 중 오류: {e}")

    print("\n30초 후 브라우저를 종료합니다...")
    time.sleep(30)
    browser.close()
