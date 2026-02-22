const pptxgen = require('pptxgenjs');
const html2pptx = require('../scripts/html2pptx');
const path = require('path');

async function createPresentation() {
    const pptx = new pptxgen();
    pptx.layout = 'LAYOUT_16x9';
    pptx.author = 'Claude Code';
    pptx.title = 'Claude Code SKILLS 소개';
    pptx.subject = 'SKILLS 개요 및 활용 가이드';

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
            const { slide } = await html2pptx(htmlFile, pptx);
            console.log(`  ✓ Slide ${i + 1} created successfully`);
        } catch (error) {
            console.error(`  ✗ Error on slide ${i + 1}:`, error.message);
            throw error;
        }
    }

    const outputFile = path.join(__dirname, 'SKILLS_Introduction.pptx');
    await pptx.writeFile({ fileName: outputFile });

    console.log(`\n✓ Presentation created successfully!`);
    console.log(`  Output: ${outputFile}`);

    return outputFile;
}

createPresentation().catch(error => {
    console.error('\n✗ Failed to create presentation:', error);
    process.exit(1);
});
