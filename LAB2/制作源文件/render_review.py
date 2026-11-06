"""Render report contact sheet and selected full-size pages outside submission."""
from pathlib import Path
import json
import pymupdf
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
pdf = next(ROOT.glob('*/*.pdf'))
out = Path(r'C:\Users\11690\AppData\Local\Temp\opencode\lab2-review')
out.mkdir(exist_ok=True)
doc = pymupdf.open(pdf)
thumbs = []
bounds = []
for i, page in enumerate(doc):
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            for span in line['spans']:
                x0, y0, x1, y1 = span['bbox']
                if min(x0, y0) < -1 or x1 > page.rect.width + 1 or y1 > page.rect.height + 1:
                    bounds.append([i + 1, span['text'], span['bbox']])
    pix = page.get_pixmap(matrix=pymupdf.Matrix(.55, .55), alpha=False)
    im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    im.thumbnail((270, 350))
    tile = Image.new('RGB', (290, 385), '#DCE5E9')
    tile.paste(im, ((290 - im.width) // 2, 5))
    ImageDraw.Draw(tile).text((12, 360), f'Page {i + 1}', fill='black')
    thumbs.append(tile)
for start in range(0, len(thumbs), 12):
    sheet = Image.new('RGB', (290 * 4, 385 * 3), 'white')
    for j, tile in enumerate(thumbs[start:start + 12]):
        sheet.paste(tile, ((j % 4) * 290, (j // 4) * 385))
    sheet.save(out / f'contact-{start // 12 + 1}.png')
for idx in sorted(set([0, 1, 5, 8, 9, 10, 11, 14, 18, len(doc) - 1])):
    doc[idx].get_pixmap(matrix=pymupdf.Matrix(1.2, 1.2), alpha=False).save(out / f'page-{idx + 1}.png')
assert not bounds, bounds
print(json.dumps({'pages': len(doc), 'out_of_page_text_spans': bounds, 'review_images': str(out)}, ensure_ascii=False))
