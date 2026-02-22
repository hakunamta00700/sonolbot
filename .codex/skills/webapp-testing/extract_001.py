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
        # 리다이렉트 발생 시 현재 URL 확인
        print(f"리다이렉트 발생, 현재 URL: {page.url}")
        if 'cardpackage' not in page.url:
            # 다시 시도
            time.sleep(2)
            page.goto('https://jwdtm.com/adm/cardpackage', wait_until='domcontentloaded')

    page.wait_for_load_state('networkidle')
    time.sleep(2)

    district_num = '001'
    print(f"{district_num}번 검색 중...")
    search_input = page.locator('#sear_package_name')
    search_input.fill(district_num)
    time.sleep(0.5)

    search_button = page.locator('button:has-text("검색")').first
    search_button.click()
    time.sleep(2)
    page.wait_for_load_state('networkidle')

    print(f"{district_num}번 패키지 찾는 중...")
    rows = page.locator('table tbody tr').all()

    found = False
    for row in rows:
        try:
            first_td = row.locator('td').first
            td_text = first_td.text_content().strip()

            # 텍스트 색상 확인 (검정색 또는 짙은 회색)
            color = first_td.evaluate('el => window.getComputedStyle(el).color')

            # rgb(0, 0, 0) 검정색 또는 rgb(51, 51, 51) 짙은 회색
            if td_text == district_num and ('rgb(0, 0, 0)' in color or 'rgb(51, 51, 51)' in color):
                print(f"{district_num}번 패키지 발견 (색상: {color}), 클릭합니다...")
                row.scroll_into_view_if_needed()
                time.sleep(0.5)
                row.click()
                found = True
                break
        except:
            continue

    if not found:
        print(f"{district_num}번 검정색 구역을 찾지 못했습니다.")
        browser.close()
        exit()

    print("클릭 후 대기 중 (5초)...")
    time.sleep(3)
    page.wait_for_load_state('networkidle')
    time.sleep(2)

    # 스크린샷
    screenshot_path = os.path.join(save_dir, f"{district_num}_clicked.png")
    page.screenshot(path=screenshot_path, full_page=True)
    print(f"스크린샷 저장: {screenshot_path}")

    # 등록된 구역 리스트 찾기
    print("\n=== 등록된 구역 리스트 추출 ===")

    # DataTable이 동적으로 렌더링될 수 있으므로 추가 대기
    time.sleep(2)

    # 모든 테이블 확인
    tables = page.locator('table').all()
    print(f"총 {len(tables)}개의 테이블 발견")

    district_data = []

    for idx, table in enumerate(tables):
        try:
            # 헤더 확인
            headers = table.locator('thead th, thead td').all()
            header_texts = [h.text_content().strip() for h in headers]

            if '구역번호' in header_texts and '구역명칭' in header_texts:
                print(f"\n[테이블 {idx}] 등록된 구역 리스트 테이블 발견!")
                print(f"헤더: {header_texts}")

                # 구역번호와 구역명칭의 인덱스 찾기
                num_idx = header_texts.index('구역번호')
                name_idx = header_texts.index('구역명칭')

                # tbody의 모든 행 가져오기
                tbody_rows = table.locator('tbody tr').all()
                print(f"총 {len(tbody_rows)}개의 행 발견")

                if len(tbody_rows) == 0:
                    # DataTable이 동적으로 렌더링되는 경우, td를 직접 찾기
                    print("tbody tr이 없습니다. 다른 방법으로 데이터 추출 시도...")

                    # 4자리 숫자 패턴으로 구역번호 찾기
                    all_cells = table.locator('td').all()
                    print(f"총 {len(all_cells)}개의 td 발견")

                    # 셀들을 순회하며 구역번호 패턴 찾기
                    i = 0
                    while i < len(all_cells):
                        try:
                            cell_text = all_cells[i].text_content().strip()
                            # 4자리 숫자인지 확인
                            if len(cell_text) == 4 and cell_text.isdigit():
                                # 다음 셀이 구역명칭일 가능성
                                if i + 1 < len(all_cells):
                                    next_cell_text = all_cells[i + 1].text_content().strip()
                                    if next_cell_text:  # 비어있지 않으면
                                        district_data.append({
                                            'number': cell_text,
                                            'name': next_cell_text
                                        })
                                        print(f"  구역번호: {cell_text}, 구역명칭: {next_cell_text}")
                        except:
                            pass
                        i += 1
                else:
                    # 정상적으로 tr이 있는 경우
                    for row in tbody_rows:
                        try:
                            cells = row.locator('td').all()
                            if len(cells) > max(num_idx, name_idx):
                                number = cells[num_idx].text_content().strip()
                                name = cells[name_idx].text_content().strip()

                                if number and name:
                                    district_data.append({
                                        'number': number,
                                        'name': name
                                    })
                                    print(f"  구역번호: {number}, 구역명칭: {name}")
                        except Exception as e:
                            print(f"  행 처리 중 오류: {e}")
                            continue

                break
        except Exception as e:
            print(f"테이블 {idx} 분석 중 오류: {e}")
            continue

    # 결과를 txt 파일로 저장
    if district_data:
        txt_path = os.path.join(save_dir, f"{district_num}.txt")
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(f"구역 패키지 {district_num}번\n")
            f.write("=" * 40 + "\n\n")
            for data in district_data:
                f.write(f"구역번호: {data['number']}\n")
                f.write(f"구역명칭: {data['name']}\n")
                f.write("-" * 40 + "\n")
        print(f"\n데이터 저장 완료: {txt_path}")
        print(f"총 {len(district_data)}개의 구역 정보 저장됨")
    else:
        print("\n추출된 데이터가 없습니다.")

    print("\n10초 후 브라우저를 종료합니다...")
    time.sleep(10)
    browser.close()
