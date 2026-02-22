const pptxgen = require('pptxgenjs');
const html2pptx = require('../scripts/html2pptx');
const path = require('path');
const fs = require('fs');

async function createPresentation() {
    const pptx = new pptxgen();
    pptx.layout = 'LAYOUT_16x9';
    pptx.author = 'Claude Code';
    pptx.title = 'Claude Code SKILLS 소개';
    pptx.subject = 'SKILLS 개요 및 활용 가이드';

    // Read background image and convert to base64 data URI
    const bgImagePath = path.join(__dirname, 'gradient_background.png');
    const bgImageBuffer = fs.readFileSync(bgImagePath);
    const bgImageData = `data:image/png;base64,${bgImageBuffer.toString('base64')}`;

    const slides = [
        'slide1.html',
        'slide2.html',
        'slide3.html',
        'slide4.html',
        'slide5.html'
    ];

    console.log('Converting HTML slides to PowerPoint...\n');

    for (let i = 0; i < slides.length; i++) {
        const htmlFile = path.join(__dirname, slides[i]);
        console.log(`Processing ${slides[i]}...`);

        try {
            // Create slide and add background FIRST
            const slide = pptx.addSlide();

            slide.addImage({
                data: bgImageData,
                x: 0,
                y: 0,
                w: '100%',
                h: '100%',
                sizing: { type: 'cover' }
            });

            // Then add HTML content on top
            await html2pptx(htmlFile, pptx, { slide });

            console.log(`  ✓ Slide ${i + 1} created successfully`);
        } catch (error) {
            console.error(`  ✗ Error on slide ${i + 1}:`, error.message);
            throw error;
        }
    }

    const outputFile = path.join(__dirname, 'SKILLS_Introduction_v2.pptx');
    await pptx.writeFile({ fileName: outputFile });

    console.log(`\n✓ Presentation created successfully!`);
    console.log(`  Output: ${outputFile}`);

    return outputFile;
}

createPresentation().catch(error => {
    console.error('\n✗ Failed to create presentation:', error);
    process.exit(1);
});
