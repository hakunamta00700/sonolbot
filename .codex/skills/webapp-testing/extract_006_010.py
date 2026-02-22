from playwright.sync_api import sync_playwright
import time
import os

# 저장 디렉토리
save_dir = r"E:\CLAUDE_PROJECT\district\아파트패키지_원본"
os.makedirs(save_dir, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    # 페이지 이동
    print("구역카드 패키지 페이지로 이동 중...")
    page.goto('https://jwdtm.com/adm/cardpackage', wait_until='domcontentloaded', timeout=60000)
    page.wait_for_load_state('networkidle')
    time.sleep(2)

    print("✓ 페이지 로드 완료\n")

    # 006~010번만 처리
    districts = ['006', '007', '008', '009', '010']
    success_count = 0
    no_data_count = 0
    not_found_count = 0

    for district_num in districts:
        print(f"\n{'='*60}")
        print(f"[{districts.index(district_num) + 1}/{len(districts)}] {district_num}번 구역 패키지 처리 중...")
        print(f"{'='*60}")

        # 검색창 찾기
        search_input = page.locator('#SearchString')
        search_input.clear()
        search_input.fill(district_num)
        time.sleep(0.5)

        # 검색 버튼 클릭
        search_button = page.locator('button:has-text("검색")')
        search_button.click()
        time.sleep(1)
        page.wait_for_load_state('networkidle')

        # 검색 결과에서 해당 구역 찾기 (왼쪽 검색 결과 테이블만)
        rows = page.locator('#divCoordCardPackage tbody tr').all()

        # No Data 체크 (검색 결과가 없는 경우)
        if len(rows) == 1:
            first_cell = rows[0].locator('td').first
            if first_cell.text_content().strip() == 'No Data':
                print(f"  ⊘ {district_num}번 검색 결과 없음 (No Data) - 건너뜀")
                not_found_count += 1
                continue

        found = False
        for row in rows:
            try:
                first_td = row.locator('td').first
                td_text = first_td.text_content().strip()

                # 정확히 일치하는지 확인
                if td_text == district_num:
                    # 텍스트 색상 확인
                    color = first_td.evaluate('el => window.getComputedStyle(el).color')

                    # 검정색 또는 짙은 회색인 경우만 처리 (빨간색 제외)
                    if 'rgb(0, 0, 0)' in color or 'rgb(51, 51, 51)' in color:
                        print(f"  ✓ {district_num}번 발견 (색상: {color})")
                        row.scroll_into_view_if_needed()
                        time.sleep(0.3)
                        row.click()
                        found = True
                        break
            except:
                continue

        if not found:
            print(f"  ✗ {district_num}번 구역 없음 또는 사용불가 - 건너뜀")
            not_found_count += 1
            continue

        # 클릭 후 중앙 영역의 DataTable 렌더링 대기
        print(f"  중앙 영역 DataTable 렌더링 대기 중...")
        time.sleep(2)
        page.wait_for_load_state('networkidle')
        time.sleep(1.5)

        # 중앙 영역에서 등록된 구역 리스트 추출
        district_data = []

        # 중앙 영역 테이블 (등록된 구역 리스트)
        center_table = page.locator('#divAddedCoordCard')

        try:
            print(f"  ✓ 중앙 영역 테이블 확인")

            # tbody 행 가져오기
            tbody_rows = center_table.locator('tbody tr').all()
            print(f"  tbody에 {len(tbody_rows)}개 행")

            # No Data 또는 빈 메시지 체크
            if len(tbody_rows) == 1:
                first_cell = tbody_rows[0].locator('td').first
                first_cell_text = first_cell.text_content().strip()
                if first_cell_text in ['No Data', '-', '먼저 패키지를 선택해주세요']:
                    print(f"  ⊘ {district_num}번 등록된 구역 없음 ({first_cell_text}) - 건너뜀")
                    no_data_count += 1
                    continue

            if len(tbody_rows) == 0:
                # DataTable 동적 렌더링: td를 직접 찾기
                print("  tbody tr이 0개, td 직접 추출 시도...")
                all_cells = center_table.locator('td').all()
                print(f"  전체 td 개수: {len(all_cells)}")

                # 처음 10개 td의 내용 출력 (디버그)
                for debug_i in range(min(10, len(all_cells))):
                    try:
                        debug_text = all_cells[debug_i].text_content().strip()
                        print(f"    td[{debug_i}]: '{debug_text}'")
                    except:
                        pass

                i = 0
                while i < len(all_cells):
                    try:
                        cell_text = all_cells[i].text_content().strip()
                        # 4자리 숫자인지 확인
                        if len(cell_text) == 4 and cell_text.isdigit():
                            if i + 1 < len(all_cells):
                                next_cell_text = all_cells[i + 1].text_content().strip()
                                # '(사용중단)' 문구 제거
                                next_cell_text = next_cell_text.replace('(사용중단)', '').strip()
                                if next_cell_text and next_cell_text != 'No Data':
                                    district_data.append({
                                        'number': cell_text,
                                        'name': next_cell_text
                                    })
                                    print(f"    - {cell_text}: {next_cell_text}")
                    except:
                        pass
                    i += 1
            else:
                # 정상적으로 tr이 있는 경우
                for row in tbody_rows:
                    try:
                        cells = row.locator('td').all()
                        if len(cells) >= 2:
                            number = cells[0].text_content().strip()
                            name = cells[1].text_content().strip()
                            # '(사용중단)' 문구 제거
                            name = name.replace('(사용중단)', '').strip()

                            if number and name and number not in ['No Data', '-']:
                                district_data.append({
                                    'number': number,
                                    'name': name
                                })
                                print(f"    - {number}: {name}")
                    except:
                        continue

        except Exception as e:
            print(f"  오류: {e}")
            no_data_count += 1
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
            print(f"  ✓ 저장 완료: {txt_path} ({len(district_data)}개 구역)")
            success_count += 1
        else:
            print(f"  ⊘ {district_num}번 데이터 없음 - 건너뜀")
            no_data_count += 1

        # 다음 검색을 위해 짧은 대기
        time.sleep(0.5)

    # 최종 결과
    print(f"\n{'='*60}")
    print(f"전체 작업 완료!")
    print(f"{'='*60}")
    print(f"성공: {success_count}개")
    print(f"No Data: {no_data_count}개")
    print(f"찾을 수 없음: {not_found_count}개")
    print(f"총: {success_count + no_data_count + not_found_count}/{len(districts)}")

    print("\n10초 후 브라우저를 종료합니다...")
    time.sleep(10)
    browser.close()
