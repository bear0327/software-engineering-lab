"""Artifact checks plus real local-browser prototype smoke tests. No server data."""
from __future__ import annotations
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from PIL import Image, ImageDraw
import pymupdf as fitz
from playwright.sync_api import sync_playwright
from ui_design import font

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / '制作源文件'
PACKAGE = ROOT / '实验2_241820122_商世雄'


def main():
    results = {}
    sources = sorted((PACKAGE / 'UML').glob('*.puml'))
    assert len(sources) == 9
    for s in sources:
        text = s.read_text(encoding='utf-8')
        assert text.startswith('@startuml') and text.rstrip().endswith('@enduml')
        with Image.open(s.with_suffix('.png')) as im:
            assert min(im.size) > 300, (s.name, im.size)
            # PlantUML stores its source/metadata in PNG: never accept an error render.
            assert 'Syntax Error' not in str(im.info)
    results['plantuml'] = '9 sources and 9 valid PNGs; 7 UML types'
    manifest = json.loads((SRC / 'ui_manifest.json').read_text(encoding='utf-8'))
    assert len(manifest) == 16
    tree = ET.parse(SRC / '酒店预订UI.drawio')
    assert len(tree.findall('diagram')) == 16
    assert all(len(d.findall('.//mxCell')) > (25 if d.attrib['id'] == 'ui-16' else 40) for d in tree.findall('diagram'))
    violations = []
    for p in manifest:
        with Image.open(PACKAGE / 'UI界面' / p['image']) as im:
            assert im.size == (p['w'] * 2, p['h'] * 2)
        ET.parse(SRC / p['svg'])
        draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        for n in p['nodes']:
            w = n.get('w', 0)
            h = n.get('h', n.get('size', 0) * 1.5)
            if n['kind'] == 'text':
                w = draw.textlength(n['text'], font=font(n['size'], n['bold']))
            if n['x'] < 0 or n['y'] < 0 or n['x'] + w > p['w'] + 2 or n['y'] + h > p['h'] + 2:
                violations.append((p['key'], n))
    assert not violations, violations
    results['ui'] = '16 native editable draw.io pages; PNG/SVG valid; all element bounds inside canvas'
    report = fitz.open(PACKAGE / '实验报告.pdf')
    text = '\n'.join(p.get_text() for p in report)
    for keyword in ['酒店预订系统', '241820122', 'AI辅助', '待确认', 'REQ-026']:
        assert keyword in text, keyword
    assert all(p.get_text().strip() for p in report)
    for p in manifest:
        assert 'UI-' + p['key'] in text
    fonts = sorted({f[3] for page in report for f in page.get_fonts()})
    assert not any('bold' in name.lower() or 'yahei' in name.lower() for name in fonts)
    for page in report:
        for drawing in page.get_drawings():
            assert drawing['fill'] in (None, (1.0, 1.0, 1.0)), (page.number + 1, drawing['fill'])
    results['pdf'] = {'pages': len(report), 'all_pages_have_text': True, 'all_ui_included': True, 'fonts': fonts, 'no_bold_font_or_background_panels': True}
    with zipfile.ZipFile(ROOT / (PACKAGE.name + '.zip')) as z:
        assert len(z.namelist()) == 35
        assert not any('/.git/' in n for n in z.namelist())
        for f in PACKAGE.rglob('*'):
            if f.is_file():
                assert z.read(f.relative_to(ROOT).as_posix()) == f.read_bytes()
    results['zip'] = 'exact 35 expected files; all bytes match package; no git/temp/source scripts'

    checks = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe', headless=True)
        page = browser.new_page(viewport={'width': 1600, 'height': 1200})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto((SRC / '交互原型.html').as_uri())
        page.wait_for_selector('#canvas button')
        assert page.title() == '泊岸酒店 · LAB2交互原型'
        page.locator('#pages').select_option('02')
        page.locator('[data-name="checkOut"]').fill('2026-11-09')
        page.get_by_role('button', name='查询空房', exact=True).click()
        assert '离店日期必须晚于入住日期' in page.locator('#message').inner_text()
        checks.append('invalid query date rejected')
        page.locator('#close').click()
        page.locator('#pages').select_option('04')
        page.get_by_role('button', name='演示提交前价格变化', exact=True).click()
        assert '¥678' in page.locator('#message').inner_text()
        page.locator('#close').click()
        page.get_by_role('button', name='确认报价并提交', exact=True).click()
        assert '提交成功' in page.locator('#message').inner_text()
        assert page.evaluate('state.total') == 678
        page.locator('#close').click()
        checks.append('price change requires second acceptance before order creation')
        page.locator('#pages').select_option('06')
        old = page.evaluate('JSON.stringify(state)')
        page.get_by_role('button', name='演示新日期无房：原单保留', exact=True).click()
        assert page.evaluate('JSON.stringify(state)') == old
        page.locator('#close').click()
        page.get_by_role('button', name='接受新报价并保存', exact=True).click()
        assert page.evaluate('state.total') == 299 and page.evaluate('state.nights') == 1
        page.locator('#close').click()
        checks.append('modify failure keeps original; shortened stay updates demo total')
        page.locator('#pages').select_option('07')
        page.get_by_role('button', name='取消本人订单', exact=True).click()
        page.locator('#close').click()
        page.get_by_role('button', name='取消本人订单', exact=True).click()
        assert '不重复释放' in page.locator('#message').inner_text()
        page.locator('#close').click()
        checks.append('duplicate cancellation blocked')
        page.locator('#pages').select_option('09')
        page.locator('[data-name="supply"]').fill('1')
        page.get_by_role('button', name='保存当日变更', exact=True).click()
        assert '不能低于已有占用' in page.locator('#message').inner_text()
        page.locator('#close').click()
        checks.append('supply below reservations rejected')
        page.locator('#pages').select_option('11')
        page.on('dialog', lambda dialog: dialog.accept())
        page.get_by_role('button', name='记录核验并办理入住', exact=True).click()
        assert page.evaluate('state.stay') == '已入住'
        page.locator('#close').click()
        page.get_by_role('button', name='记录核验并办理入住', exact=True).click()
        assert '重复入住被阻止' in page.locator('#message').inner_text()
        page.locator('#close').click()
        page.get_by_role('button', name='已入住订单正常退房', exact=True).click()
        assert page.evaluate('state.stay') == '已退房'
        page.locator('#close').click()
        checks.append('check-in repeat blocked; normal check-out succeeds')
        page.locator('#pages').select_option('12')
        page.get_by_role('button', name='标记停业，停止新预订', exact=True).click()
        assert page.evaluate('state.hotel') == '停业'
        page.locator('#close').click()
        page.locator('#pages').select_option('04')
        page.get_by_role('button', name='确认报价并提交', exact=True).click()
        assert '酒店已停业' in page.locator('#message').inner_text()
        checks.append('closed hotel blocks demo bookings')
        assert not errors, errors
        browser.close()
    results['prototype_browser'] = {'checks': checks, 'javascript_errors': errors, 'scope': 'UI demonstration only, not real business tests'}
    (SRC / '检查结果.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
