from playwright.sync_api import sync_playwright
import os
import time
from pathlib import Path

# Get the HTML file path
html_file = Path(__file__).with_name("pattern_01_wave_interference.html").resolve()
file_url = html_file.as_uri()

# Output directory
output_dir = os.path.join(os.path.expanduser("~"), "Downloads")
os.makedirs(output_dir, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)  # Non-headless to see what's happening
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})

    print(f"Opening: {file_url}")
    page.goto(file_url)

    # Wait for the canvas to be ready
    page.wait_for_selector('canvas', timeout=10000)
    time.sleep(2)  # Extra time for rendering

    # Configure for Naver-style: clean, bright, professional colors
    # Set to bright, soft colors - like Naver's clean aesthetic

    print("Configuring Image 1: Soft Blue & Purple gradient")
    # Image 1: Soft blue and purple (clean, professional)
    page.fill('#seed-input', '12345')
    page.fill('#waveCount', '5')
    page.fill('#frequencyScale', '1.2')
    page.fill('#amplitude', '0.8')
    page.fill('#rotation', '0')
    page.fill('#colorIntensity', '0.8')

    # Soft blue and purple colors (Naver-style clean)
    page.evaluate("""
        document.getElementById('color1').value = '#E8F4F8';
        document.getElementById('color1-value').textContent = '#E8F4F8';
        document.getElementById('color2').value = '#B8E0F6';
        document.getElementById('color2-value').textContent = '#B8E0F6';
        document.getElementById('color3').value = '#D4E8F5';
        document.getElementById('color3-value').textContent = '#D4E8F5';
        document.getElementById('bgColor').value = '#FFFFFF';
        document.getElementById('bgColor-value').textContent = '#FFFFFF';
    """)

    # Trigger regeneration
    page.click('button:has-text("Reset")')
    time.sleep(1)

    # Update colors again after reset
    page.evaluate("""
        const params = {
            seed: 12345,
            waveCount: 5,
            frequencyScale: 1.2,
            amplitude: 0.8,
            rotation: 0,
            colorIntensity: 0.8,
            colors: ['#E8F4F8', '#B8E0F6', '#D4E8F5'],
            bgColor: '#FFFFFF'
        };
        document.getElementById('seed-input').value = params.seed;

        let canvas = document.querySelector('canvas');
        if (canvas) {
            let ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        }

        // Manually trigger regeneration with new colors
        generatePattern();
    """)

    time.sleep(2)

    # Screenshot 1
    output1 = os.path.join(output_dir, "ppt_background_1_soft_blue.png")
    page.locator('#canvas-container').screenshot(path=output1)
    print(f"✓ Saved: {output1}")

    # Image 2: Soft green and mint (clean, fresh - Naver green theme)
    print("\nConfiguring Image 2: Soft Green & Mint gradient")
    page.evaluate("""
        document.getElementById('seed-input').value = '54321';
        document.getElementById('waveCount').value = '4';
        document.getElementById('frequencyScale').value = '1.8';
        document.getElementById('amplitude').value = '1.2';
        document.getElementById('rotation').value = '45';
        document.getElementById('colorIntensity').value = '0.9';

        document.getElementById('color1').value = '#E8F8F5';
        document.getElementById('color1-value').textContent = '#E8F8F5';
        document.getElementById('color2').value = '#C8EED8';
        document.getElementById('color2-value').textContent = '#C8EED8';
        document.getElementById('color3').value = '#D5F5E3';
        document.getElementById('color3-value').textContent = '#D5F5E3';
        document.getElementById('bgColor').value = '#FFFFFF';
        document.getElementById('bgColor-value').textContent = '#FFFFFF';
    """)

    # Trigger regeneration
    page.evaluate("generatePattern()")
    time.sleep(2)

    # Screenshot 2
    output2 = os.path.join(output_dir, "ppt_background_2_soft_green.png")
    page.locator('#canvas-container').screenshot(path=output2)
    print(f"✓ Saved: {output2}")

    print(f"\n✓ Complete! Images saved to: {output_dir}")

    browser.close()
