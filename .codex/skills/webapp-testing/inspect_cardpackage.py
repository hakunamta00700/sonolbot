from playwright.sync_api import sync_playwright
import time
import os

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

    # 초기 페이지 스크린샷
    print("1. 초기 페이지 스크린샷 저장 중...")
    page.screenshot(path='cardpackage_initial.png', full_page=True)
    print("   → cardpackage_initial.png 저장 완료")

    # 페이지 HTML 구조 저장
    print("2. 페이지 HTML 구조 저장 중...")
    html_content = page.content()
    with open('cardpackage_page.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    print("   → cardpackage_page.html 저장 완료")

    # 입력 요소들 찾기
    print("\n3. 입력 요소 분석 중...")
    inputs = page.locator('input').all()
    print(f"   총 {len(inputs)}개의 input 요소 발견")
    for idx, inp in enumerate(inputs):
        try:
            inp_type = inp.get_attribute('type')
            inp_placeholder = inp.get_attribute('placeholder')
            inp_id = inp.get_attribute('id')
            inp_name = inp.get_attribute('name')
            inp_class = inp.get_attribute('class')
            print(f"   [{idx}] type={inp_type}, id={inp_id}, name={inp_name}, placeholder={inp_placeholder}, class={inp_class}")
        except:
            pass

    print("\n테스트를 위해 '001'을 검색해보겠습니다.")
    print("검색창으로 보이는 input 찾기...")

    # 검색창으로 보이는 input 찾기 (일반적으로 text 타입)
    search_input = None
    for inp in inputs:
        try:
            inp_type = inp.get_attribute('type')
            inp_id = inp.get_attribute('id')
            inp_name = inp.get_attribute('name')

            # cardpackage 페이지의 검색창 찾기
            if inp_id == 'sear_name' or inp_name == 'sear_name':
                search_input = inp
                print(f"   → 검색창 발견: id={inp_id}, name={inp_name}")
                break
        except:
            pass

    if search_input is None:
        print("   ⚠ 검색창을 찾을 수 없습니다. 첫 번째 text input 사용")
        for inp in inputs:
            try:
                inp_type = inp.get_attribute('type')
                if inp_type in ['text', 'search', None]:
                    search_input = inp
                    break
            except:
                pass

    if search_input:
        # 검색창에 001 입력
        print(f"\n4. 검색창에 '001' 입력 중...")
        search_input.fill('001')
        time.sleep(1)

        # 입력 후 스크린샷
        page.screenshot(path='cardpackage_after_input.png', full_page=True)
        print("   → cardpackage_after_input.png 저장 완료")

        # 엔터 또는 검색 버튼 클릭
        print("5. Enter 키 누르기...")
        search_input.press('Enter')
        time.sleep(2)
        page.wait_for_load_state('networkidle')

        # 검색 결과 스크린샷
        page.screenshot(path='cardpackage_search_result.png', full_page=True)
        print("   → cardpackage_search_result.png 저장 완료")

        # 검색 결과 HTML 저장
        html_content = page.content()
        with open('cardpackage_search_result.html', 'w', encoding='utf-8') as f:
            f.write(html_content)
        print("   → cardpackage_search_result.html 저장 완료")

        # 클릭 가능한 요소들 찾기
        print("\n6. '001' 텍스트를 포함한 요소 찾기...")
        elements_with_001 = page.locator('text="001"').all()
        print(f"   총 {len(elements_with_001)}개의 '001' 요소 발견")

        for idx, elem in enumerate(elements_with_001):
            try:
                tag = elem.evaluate('el => el.tagName')
                color = elem.evaluate('el => window.getComputedStyle(el).color')
                bg_color = elem.evaluate('el => window.getComputedStyle(el).backgroundColor')
                classes = elem.get_attribute('class')
                print(f"   [{idx}] tag={tag}, color={color}, bg={bg_color}, class={classes}")
            except:
                pass

        # 검정색 요소를 자동으로 찾아 클릭
        print("\n검정색 요소를 자동으로 찾아 클릭합니다...")
        target_elem = None
        for idx, elem in enumerate(elements_with_001):
            try:
                color = elem.evaluate('el => window.getComputedStyle(el).color')
                if 'rgb(0, 0, 0)' in color or 'rgba(0, 0, 0' in color or 'black' in color.lower():
                    print(f"   검정색 요소 발견 (인덱스: {idx})")
                    target_elem = elem
                    break
            except:
                pass

        if target_elem is None and len(elements_with_001) > 0:
            print("   검정색 요소를 찾지 못해 첫 번째 요소를 클릭합니다.")
            target_elem = elements_with_001[0]

        if target_elem:
            print(f"\n7. 선택한 요소 클릭 중...")
            target_elem.click()
            time.sleep(2)
            page.wait_for_load_state('networkidle')

            # 클릭 후 스크린샷
            page.screenshot(path='cardpackage_after_click.png', full_page=True)
            print("   → cardpackage_after_click.png 저장 완료")

            # 클릭 후 HTML 저장
            html_content = page.content()
            with open('cardpackage_after_click.html', 'w', encoding='utf-8') as f:
                f.write(html_content)
            print("   → cardpackage_after_click.html 저장 완료")

            print("\n8. 등록된 구역 리스트 찾기...")
            # 테이블, 리스트 등 찾기
            tables = page.locator('table').all()
            print(f"   - table 요소: {len(tables)}개")

            # 각 테이블의 행 개수 확인
            for t_idx, table in enumerate(tables):
                try:
                    rows = table.locator('tr').all()
                    print(f"     테이블 {t_idx}: {len(rows)}개 행")

                    # 처음 3개 행만 출력
                    for r_idx in range(min(3, len(rows))):
                        try:
                            tds = rows[r_idx].locator('td').all()
                            if len(tds) > 0:
                                texts = [td.text_content().strip() for td in tds[:3]]
                                print(f"       행 {r_idx}: {texts}")
                        except:
                            pass
                except:
                    pass

    print("\n" + "="*60)
    print("분석 완료! 30초 후 브라우저를 종료합니다.")
    print("="*60)
    time.sleep(30)

    browser.close()
