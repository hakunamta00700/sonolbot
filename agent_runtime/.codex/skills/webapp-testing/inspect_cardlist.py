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

    print("구역카드 페이지로 이동합니다...")

    # 구역카드 페이지로 이동
    page.goto('https://jwdtm.com/adm/cardlist')
    page.wait_for_load_state('networkidle')
    time.sleep(2)

    # 초기 페이지 스크린샷
    print("1. 초기 페이지 스크린샷 저장 중...")
    page.screenshot(path='cardlist_initial.png', full_page=True)
    print("   → cardlist_initial.png 저장 완료")

    # 페이지 HTML 구조 저장
    print("2. 페이지 HTML 구조 저장 중...")
    html_content = page.content()
    with open('cardlist_page.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    print("   → cardlist_page.html 저장 완료")

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
    print("첫 번째 input 요소를 사용합니다...")

    # 검색창으로 보이는 input 찾기 (일반적으로 text 타입)
    search_input = None
    for inp in inputs:
        try:
            inp_type = inp.get_attribute('type')
            if inp_type in ['text', 'search', None]:
                search_input = inp
                break
        except:
            pass

    if search_input is None and len(inputs) > 0:
        search_input = inputs[0]

    try:

        # 검색창에 001 입력
        print(f"\n4. 검색창에 '001' 입력 중...")
        search_input.fill('001')
        time.sleep(1)

        # 입력 후 스크린샷
        page.screenshot(path='cardlist_after_input.png', full_page=True)
        print("   → cardlist_after_input.png 저장 완료")

        # 엔터 또는 검색 버튼 클릭
        print("5. Enter 키 누르기...")
        search_input.press('Enter')
        time.sleep(2)
        page.wait_for_load_state('networkidle')

        # 검색 결과 스크린샷
        page.screenshot(path='cardlist_search_result.png', full_page=True)
        print("   → cardlist_search_result.png 저장 완료")

        # 검색 결과 HTML 저장
        html_content = page.content()
        with open('cardlist_search_result.html', 'w', encoding='utf-8') as f:
            f.write(html_content)
        print("   → cardlist_search_result.html 저장 완료")

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

        print("\n검정색 요소를 자동으로 찾아 클릭합니다...")

        # 검정색 요소 찾기
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

        try:
            print(f"\n7. 선택한 요소 클릭 중...")
            target_elem.click()
            time.sleep(2)
            page.wait_for_load_state('networkidle')

            # 클릭 후 스크린샷
            page.screenshot(path='cardlist_after_click.png', full_page=True)
            print("   → cardlist_after_click.png 저장 완료")

            # 클릭 후 HTML 저장
            html_content = page.content()
            with open('cardlist_after_click.html', 'w', encoding='utf-8') as f:
                f.write(html_content)
            print("   → cardlist_after_click.html 저장 완료")

            print("\n8. 지도 영역 찾기...")
            # 이미지, 캔버스, iframe 등 지도가 표시될 수 있는 요소 찾기
            images = page.locator('img').all()
            print(f"   - img 요소: {len(images)}개")

            canvases = page.locator('canvas').all()
            print(f"   - canvas 요소: {len(canvases)}개")

            iframes = page.locator('iframe').all()
            print(f"   - iframe 요소: {len(iframes)}개")

            maps = page.locator('[class*="map"], [id*="map"]').all()
            print(f"   - map 관련 요소: {len(maps)}개")

        except Exception as e:
            print(f"   오류 발생: {e}")

    except Exception as e:
        print(f"오류 발생: {e}")

    print("\n" + "="*60)
    print("분석 완료! 30초 후 브라우저를 종료합니다.")
    print("="*60)
    time.sleep(30)

    browser.close()
