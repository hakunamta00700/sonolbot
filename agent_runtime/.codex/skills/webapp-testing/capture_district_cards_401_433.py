from playwright.sync_api import sync_playwright
import time
import os

# 저장 폴더 경로 (격지)
save_dir = r"E:\CLAUDE_PROJECT\district\격지"
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

    print("구역카드 페이지로 이동합니다...")

    # 구역카드 페이지로 이동 (리다이렉트 처리)
    try:
        page.goto('https://jwdtm.com/adm/cardlist', timeout=10000)
    except:
        # 리다이렉트로 인한 오류 무시하고 다시 시도
        time.sleep(2)
        page.goto('https://jwdtm.com/adm/cardlist', wait_until='domcontentloaded')

    page.wait_for_load_state('networkidle')
    time.sleep(2)

    # 401부터 433까지 범위
    success_count = 0
    failed_list = []

    for i in range(401, 434):
        district_num = f"{i:03d}"
        print(f"\n처리 중: {district_num}번 구역 ({i-400}/{434-401})")

        try:
            # 페이지 새로고침하여 초기 상태로
            page.goto('https://jwdtm.com/adm/cardlist')
            page.wait_for_load_state('networkidle')
            time.sleep(1)

            # 검색창에 구역번호 입력 (id="sear_name")
            search_input = page.locator('#sear_name')
            search_input.fill(district_num)
            time.sleep(0.5)

            # 검색 버튼 클릭
            search_button = page.locator('button:has-text("검색")')
            search_button.click()
            time.sleep(2)
            page.wait_for_load_state('networkidle')

            # 테이블에서 정확히 일치하는 구역 찾기
            # tbody 안의 tr 요소들 확인
            rows = page.locator('tbody tr').all()

            clicked = False
            for row in rows:
                try:
                    # 첫 번째 td (구역번호) 가져오기
                    first_td = row.locator('td').first
                    td_text = first_td.text_content().strip()

                    # 정확히 일치하는지 확인
                    if td_text == district_num:
                        # 색상 확인 (검정색인지)
                        row_style = row.get_attribute('style')

                        # 빨간색(사용중단)이 아닌 경우만 클릭
                        if row_style is None or 'rgb(255, 0, 0)' not in row_style:
                            print(f"  → {district_num}번 구역 발견, 스크롤 후 클릭합니다...")

                            # 요소가 화면에 보이도록 스크롤
                            row.scroll_into_view_if_needed()
                            time.sleep(0.5)

                            # 클릭
                            row.click()
                            clicked = True
                            break
                except Exception as e:
                    continue

            if not clicked:
                print(f"  ⚠ {district_num}번 구역을 찾을 수 없습니다.")
                failed_list.append(district_num)
                continue

            # 지도 로딩 대기
            time.sleep(3)
            page.wait_for_load_state('networkidle')

            # 지도 영역 확인 및 스크린샷 저장
            print(f"  → 지도 요소를 찾는 중...")

            # 여러 지도 관련 요소 확인
            map_container = page.locator('#map-container')
            map_element = page.locator('#map')
            map_title = page.locator('#map_title')

            print(f"     - #map-container 발견: {map_container.count()}개")
            print(f"     - #map 발견: {map_element.count()}개")
            print(f"     - #map_title 발견: {map_title.count()}개")

            # 지도 제목 확인 및 파일명 생성
            title_text = ""
            if map_title.count() > 0:
                title_text = map_title.text_content().strip()
                print(f"     - 지도 제목: '{title_text}'")

            # 파일명 생성 (구역번호 + 구역명칭)
            if title_text:
                # 파일명에 사용할 수 없는 문자 제거
                safe_title = title_text.replace('/', '-').replace('\\', '-').replace(':', '-').replace('*', '').replace('?', '').replace('"', '').replace('<', '').replace('>', '').replace('|', '')
                filename = f"{district_num}({safe_title}).png"
            else:
                filename = f"{district_num}.png"

            # 지도 스크린샷 저장
            if map_element.count() > 0:
                screenshot_path = os.path.join(save_dir, filename)
                map_element.screenshot(path=screenshot_path)
                print(f"  ✓ {filename} 저장 완료 (#map 요소 캡쳐)")
                success_count += 1
            elif map_container.count() > 0:
                # map_container 전체 캡쳐
                screenshot_path = os.path.join(save_dir, filename)
                map_container.screenshot(path=screenshot_path)
                print(f"  ✓ {filename} 저장 완료 (#map-container 요소 캡쳐)")
                success_count += 1
            else:
                print(f"  ⚠ 지도 영역을 찾을 수 없습니다.")
                # 전체 페이지 스크린샷으로 디버깅
                debug_path = os.path.join(save_dir, f"{district_num}_debug.png")
                page.screenshot(path=debug_path, full_page=True)
                print(f"  → 디버그용 전체 스크린샷 저장: {district_num}_debug.png")
                failed_list.append(district_num)

        except Exception as e:
            print(f"  ✗ 오류 발생: {str(e)}")
            failed_list.append(district_num)
            continue

        # 진행 상황 주기적으로 출력
        if (i - 400) % 10 == 0:
            print(f"\n--- 진행률: {i-400}/33 ({success_count}개 성공) ---")

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
