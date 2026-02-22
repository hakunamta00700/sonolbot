from playwright.sync_api import sync_playwright
import time
import os

# 저장 폴더 경로
save_dir = r"E:\CLAUDE_PROJECT\district\호별"
os.makedirs(save_dir, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    # 로그인 페이지로 이동
    print("브라우저를 열고 있습니다...")
    page.goto('https://jwdtm.com')
    page.wait_for_load_state('networkidle')

    print("\n" + "="*60)
    print("로그인을 완료한 후 Enter를 눌러주세요...")
    print("="*60 + "\n")

    # 사용자가 로그인할 시간 대기
    try:
        input()
    except:
        time.sleep(30)

    print("자동화를 시작합니다...")

    # 구역카드 페이지로 이동
    page.goto('https://jwdtm.com/adm/cardlist')
    page.wait_for_load_state('networkidle')
    time.sleep(2)

    # 001부터 332까지 반복
    success_count = 0
    failed_list = []

    for i in range(1, 333):
        district_num = f"{i:03d}"
        print(f"\n처리 중: {district_num}번 구역 ({i}/332)")

        try:
            # 페이지 새로고침하여 초기 상태로
            page.goto('https://jwdtm.com/adm/cardlist')
            page.wait_for_load_state('networkidle')
            time.sleep(1)

            # 검색창 찾기 및 입력
            # 다양한 선택자 시도
            search_input = None
            selectors = [
                'input[type="text"]',
                'input[type="search"]',
                'input[placeholder*="검색"]',
                'input[placeholder*="구역"]',
                '#search',
                '.search-input'
            ]

            for selector in selectors:
                try:
                    if page.locator(selector).count() > 0:
                        search_input = page.locator(selector).first
                        break
                except:
                    continue

            if search_input is None:
                print(f"  ⚠ 검색창을 찾을 수 없습니다.")
                failed_list.append(district_num)
                continue

            # 검색창에 구역번호 입력
            search_input.fill(district_num)
            time.sleep(0.5)

            # 엔터 키 또는 검색 버튼 클릭
            search_input.press('Enter')
            time.sleep(1.5)

            # 검색 결과에서 정확히 일치하는 검정색 구역 찾기
            # 구역 항목 클릭 (다양한 패턴 시도)
            clicked = False

            # 텍스트가 정확히 district_num인 요소 찾기
            if page.locator(f'text="{district_num}"').count() > 0:
                elements = page.locator(f'text="{district_num}"').all()
                for element in elements:
                    try:
                        # 검정색인지 확인 (스타일 확인)
                        color = element.evaluate('el => window.getComputedStyle(el).color')
                        # RGB(0, 0, 0) 또는 검정색 계열인지 확인
                        if 'rgb(0, 0, 0)' in color or 'rgba(0, 0, 0' in color or 'black' in color:
                            element.click()
                            clicked = True
                            break
                    except:
                        # 색상 확인 실패시 그냥 클릭 시도
                        try:
                            element.click()
                            clicked = True
                            break
                        except:
                            continue

            if not clicked:
                print(f"  ⚠ {district_num}번 구역을 찾을 수 없습니다.")
                failed_list.append(district_num)
                continue

            # 지도 로딩 대기
            time.sleep(2)
            page.wait_for_load_state('networkidle')

            # 스크린샷 저장
            screenshot_path = os.path.join(save_dir, f"{district_num}.png")
            page.screenshot(path=screenshot_path, full_page=True)

            print(f"  ✓ {district_num}.png 저장 완료")
            success_count += 1

        except Exception as e:
            print(f"  ✗ 오류 발생: {str(e)}")
            failed_list.append(district_num)
            continue

    print("\n" + "="*60)
    print(f"작업 완료!")
    print(f"성공: {success_count}개")
    print(f"실패: {len(failed_list)}개")
    if failed_list:
        print(f"실패한 구역: {', '.join(failed_list)}")
    print("="*60)

    browser.close()
