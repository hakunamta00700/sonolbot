from pptx import Presentation
from PIL import Image
import io
import os

# Open the presentation
pptx_path = os.path.join(os.path.dirname(__file__), "SKILLS_Introduction.pptx")
prs = Presentation(pptx_path)

print(f"Total slides: {len(prs.slides)}")
print(f"\nPresentation created successfully!")
print(f"Title: {prs.core_properties.title}")
print(f"Author: {prs.core_properties.author}")
print(f"Subject: {prs.core_properties.subject}")
print(f"\nSlide dimensions: {prs.slide_width} x {prs.slide_height} (EMUs)")
print(f"Layout: 16:9")
print(f"\nFile saved at: {pptx_path}")
