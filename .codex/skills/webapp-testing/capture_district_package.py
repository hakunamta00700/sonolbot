from playwright.sync_api import sync_playwright
import time
import os

# 저장 폴더 경로
save_dir = r"E:\CLAUDE_PROJECT\district\아파트패키지"
os.makedirs(save_dir, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    # 로그인 페이지로 이동
    print("브라우저를 열고 있습니다...")
    page.goto('https://jwdtm.com')
    page.wait_for_load_state('networkidle')

    print("\n" + "="*60)
    print("로그인을 완료해주세요. 30초 후 자동으로 진행됩니다...")
    print("="*60 + "\n")

    # 사용자가 로그인할 시간 대기
    time.sleep(30)

    print("로그인 확인 중...")
    # 로그인 후 리다이렉트 대기
    time.sleep(2)
    page.wait_for_load_state('networkidle')

    print("구역카드 패키지 페이지로 이동합니다...")

    # 구역카드 패키지 페이지로 이동
    try:
        page.goto('https://jwdtm.com/adm/cardpackage', timeout=10000)
    except:
        time.sleep(2)
        page.goto('https://jwdtm.com/adm/cardpackage', wait_until='domcontentloaded')

    page.wait_for_load_state('networkidle')
    time.sleep(2)

    # 002번만 테스트
    success_count = 0
    failed_list = []

    for i in range(2, 3):
        district_num = f"{i:03d}"
        print(f"\n처리 중: {district_num}번 구역 ({i}/332)")

        try:
            # 페이지 새로고침하여 초기 상태로
            page.goto('https://jwdtm.com/adm/cardpackage')
            page.wait_for_load_state('networkidle')
            time.sleep(1)

            # 패키지 검색창에 구역번호 입력 (id="sear_package_name")
            search_input = page.locator('#sear_package_name')
            search_input.fill(district_num)
            time.sleep(0.5)

            # 검색 버튼 클릭 (왼쪽 패키지 검색 영역의 검색 버튼)
            search_button = page.locator('button:has-text("검색")').first
            search_button.click()
            time.sleep(2)
            page.wait_for_load_state('networkidle')

            # 왼쪽 패키지 테이블에서 정확히 일치하는 번호 찾기
            # 패키지 목록은 특정 테이블에 있음
            rows = page.locator('table tbody tr').all()

            # 패키지명도 저장하기 위해 변수 추가
            package_name = ""

            clicked = False
            for row in rows:
                try:
                    # 첫 번째 td (번호) 가져오기
                    first_td = row.locator('td').first
                    td_text = first_td.text_content().strip()

                    # 정확히 일치하는지 확인
                    if td_text == district_num:
                        print(f"  → {district_num}번 패키지 발견, 스크롤 후 클릭합니다...")

                        # 패키지명 가져오기 (두 번째 td)
                        tds = row.locator('td').all()
                        if len(tds) >= 2:
                            package_name = tds[1].text_content().strip()

                        # 요소가 화면에 보이도록 스크롤
                        row.scroll_into_view_if_needed()
                        time.sleep(0.5)

                        # 클릭 (빨간색이든 검정색이든 모두 클릭)
                        row.click()
                        clicked = True
                        break
                except Exception as e:
                    continue

            if not clicked:
                print(f"  ⚠ {district_num}번 구역을 찾을 수 없습니다.")
                failed_list.append(district_num)
                continue

            # 등록된 구역 리스트 로딩 대기
            # DataTable이 동적으로 로딩되므로 충분히 대기
            time.sleep(3)
            page.wait_for_load_state('networkidle')
            time.sleep(2)  # DataTable 렌더링 추가 대기

            # 중앙의 "등록된 구역 리스트" 수집
            print(f"  → 중앙의 등록된 구역 리스트를 찾는 중...")

            # 중앙 영역의 테이블 찾기 (제목이 "등록된 구역리스트"인 테이블)
            # "등록된 구역리스트" 텍스트를 찾아서 그 아래 테이블을 가져옴
            district_list = []

            # 방법 1: 중앙 테이블의 tbody tr 찾기
            # 페이지에 여러 테이블이 있으므로, 중앙 영역(등록된 구역리스트) 테이블만 찾아야 함

            # "등록된 구역리스트" 제목 아래의 테이블을 찾기
            # 일반적으로 이런 구조: <h3>등록된 구역리스트</h3> <table>...</table>

            # 모든 테이블을 확인하여 "구역번호", "구역명칭" 헤더가 있는 테이블 찾기
            tables = page.locator('table').all()

            for table_idx, table in enumerate(tables):
                try:
                    # 테이블 헤더 확인
                    headers = table.locator('thead th, thead td').all()
                    header_texts = [h.text_content().strip() for h in headers]

                    # "구역번호"와 "구역명칭"이 포함된 테이블 찾기
                    if '구역번호' in header_texts and '구역명칭' in header_texts:
                        print(f"     - 등록된 구역 리스트 테이블 발견 (테이블 {table_idx})")

                        # tbody의 행들 가져오기
                        tbody_rows = table.locator('tbody tr').all()
                        print(f"     - 등록된 구역 수: {len(tbody_rows)}개")

                        for row in tbody_rows:
                            try:
                                tds = row.locator('td').all()

                                if len(tds) >= 2:
                                    # 첫 번째 열: 구역번호, 두 번째 열: 구역명칭
                                    num = tds[0].text_content().strip()
                                    name = tds[1].text_content().strip()

                                    # "먼저 패키지를 선택해주세요" 같은 메시지 제외
                                    if num and name and num != '-' and '선택해주세요' not in name:
                                        # <br> 태그로 줄바꿈된 텍스트 처리 및 (사용중단) 제거
                                        name_clean = name.replace('\n', ' ').replace('(사용중단)', '').strip()
                                        district_list.append(f"{num} - {name_clean}")
                                        print(f"         {num} - {name_clean}")
                            except:
                                continue

                        break  # 찾았으면 종료
                except:
                    continue

            # 구역 리스트를 txt 파일로 저장
            if len(district_list) > 0:
                # 파일명: "번호(패키지명).txt"
                # 파일명에 사용할 수 없는 문자 제거
                safe_package_name = package_name.replace('/', '-').replace('\\', '-').replace(':', '-').replace('*', '').replace('?', '').replace('"', '').replace('<', '').replace('>', '').replace('|', '')
                filename = f"{district_num}({safe_package_name}).txt"
                txt_path = os.path.join(save_dir, filename)

                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(f"패키지 번호: {district_num}\n")
                    f.write(f"패키지명: {package_name}\n")
                    f.write(f"등록된 구역 수: {len(district_list)}\n")
                    f.write("\n")
                    for item in district_list:
                        f.write(f"{item}\n")

                print(f"  ✓ {filename} 저장 완료 ({len(district_list)}개 구역)")
                success_count += 1
            else:
                print(f"  ⚠ 등록된 구역 리스트를 찾을 수 없습니다.")
                # 디버그용 스크린샷 및 HTML 저장
                debug_path = os.path.join(save_dir, f"{district_num}_debug.png")
                page.screenshot(path=debug_path, full_page=True)
                print(f"  → 디버그용 스크린샷 저장: {district_num}_debug.png")

                debug_html_path = os.path.join(save_dir, f"{district_num}_debug.html")
                with open(debug_html_path, 'w', encoding='utf-8') as f:
                    f.write(page.content())
                print(f"  → 디버그용 HTML 저장: {district_num}_debug.html")

                failed_list.append(district_num)

        except Exception as e:
            print(f"  ✗ 오류 발생: {str(e)}")
            failed_list.append(district_num)
            continue

        # 진행 상황 주기적으로 출력
        if i % 10 == 0:
            print(f"\n--- 진행률: {i}/332 ({success_count}개 성공) ---")

    print("\n" + "="*60)
    print(f"작업 완료!")
    print(f"성공: {success_count}개")
    print(f"실패: {len(failed_list)}개")
    if failed_list:
        print(f"\n실패한 구역 목록:")
        print(", ".join(failed_list))

        # 실패 목록을 파일로 저장
        with open(os.path.join(save_dir, "failed_list.txt"), 'w', encoding='utf-8') as f:
            f.write("\n".join(failed_list))
        print(f"\n실패 목록이 {os.path.join(save_dir, 'failed_list.txt')}에 저장되었습니다.")
    print("="*60)

    time.sleep(5)
    browser.close()
