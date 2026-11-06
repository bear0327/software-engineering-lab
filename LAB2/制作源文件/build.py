"""Reproducibly build PlantUML, UI boards, plain report and exact submission ZIP."""
from __future__ import annotations
import argparse
import hashlib
import html
import json
import re
import subprocess
import zipfile
from pathlib import Path
from PIL import Image as PILImage
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, A3, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, NextPageTemplate, KeepTogether
import ui_design

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '制作源文件'
PACKAGE = ROOT / '实验2_241820122_商世雄'


def render_uml(jar):
    for path in sorted((PACKAGE / 'UML').glob('*.puml')):
        args = ['java', '-Dfile.encoding=UTF-8', '-DPLANTUML_LIMIT_SIZE=12000', '-jar', str(jar), '-charset', 'UTF-8', '-tpng', str(path)]
        result = subprocess.run(args, capture_output=True)
        if result.returncode:
            raise RuntimeError(path.name + ': ' + result.stderr.decode('utf-8', 'replace'))
        if not path.with_suffix('.png').exists():
            raise RuntimeError('Missing rendered image: ' + str(path))
    print('PlantUML: all 9 sources rendered successfully')


def make_pdf():
    pdfmetrics.registerFont(TTFont('CJK', r'C:\Windows\Fonts\msyh.ttc'))
    pdfmetrics.registerFont(TTFont('CJKBold', r'C:\Windows\Fonts\msyhbd.ttc'))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='BodyCJK', fontName='CJK', fontSize=10, leading=17, wordWrap='CJK', spaceAfter=8))
    styles.add(ParagraphStyle(name='TitleCJK', fontName='CJKBold', fontSize=24, leading=35, spaceAfter=17))
    styles.add(ParagraphStyle(name='H1CJK', fontName='CJKBold', fontSize=16, leading=25, spaceBefore=14, spaceAfter=10, keepWithNext=True))
    styles.add(ParagraphStyle(name='H2CJK', fontName='CJKBold', fontSize=12, leading=20, spaceBefore=10, spaceAfter=7, keepWithNext=True))
    styles.add(ParagraphStyle(name='TableCJK', fontName='CJK', fontSize=8.7, leading=14, wordWrap='CJK'))
    styles.add(ParagraphStyle(name='TableHeadCJK', parent=styles['TableCJK'], fontName='CJKBold'))
    styles.add(ParagraphStyle(name='CaptionCJK', fontName='CJK', fontSize=10, leading=17, textColor=colors.HexColor('#444444'), spaceAfter=12))
    dest = PACKAGE / '实验报告.pdf'
    margin = 19 * mm

    def decorate(c, doc):
        w, h = doc.pagesize
        c.saveState()
        c.setStrokeColor(colors.HexColor('#DDDDDD'))
        c.line(margin, h - 14 * mm, w - margin, h - 14 * mm)
        c.setFillColor(colors.HexColor('#555555'))
        c.setFont('CJK', 8)
        c.drawString(margin, h - 11 * mm, '实验二：软件设计与建模 / 酒店预订系统')
        c.drawString(margin, 10 * mm, '商世雄 · 241820122')
        c.drawRightString(w - margin, 10 * mm, str(doc.page))
        c.restoreState()

    # BaseDocTemplate does not automatically change the actual page media box
    # when switching templates, so a callback sets it from each frame size.
    def onpage_for(size):
        def onpage(c, doc):
            doc.pagesize = size
            c.setPageSize(size)
            decorate(c, doc)
        return onpage

    doc = BaseDocTemplate(str(dest), pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=22 * mm, bottomMargin=19 * mm, title='实验二 软件设计与建模 — 酒店预订系统', author='商世雄 241820122')
    sizes = {'text': A4, 'ui': landscape(A3), 'diagram': A3, 'wide': landscape(A3)}
    for key, size in sizes.items():
        w, h = size
        f = Frame(margin, 19 * mm, w - 2 * margin, h - 41 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        doc.addPageTemplates(PageTemplate(id=key, frames=f, onPage=onpage_for(size), pagesize=size))
    story = []
    width = A4[0] - 2 * margin
    lines = (SOURCE / '报告.md').read_text(encoding='utf-8').splitlines()

    def para(s, style='BodyCJK'):
        return Paragraph(html.escape(s), styles[style])

    def add_table(rows):
        cols = len(rows[0])
        if cols == 3:
            ratios = [.19, .47, .34]
        elif cols == 2:
            ratios = [.25, .75]
        else:
            ratios = [1 / cols] * cols
        content = [[para(v.strip(), 'TableHeadCJK' if i == 0 else 'TableCJK') for v in row] for i, row in enumerate(rows)]
        t = Table(content, colWidths=[width * r for r in ratios], repeatRows=1, hAlign='LEFT')
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F3F3F3')),
            ('LINEBELOW', (0, 0), (-1, 0), .7, colors.black), ('LINEBELOW', (0, 1), (-1, -1), .3, colors.HexColor('#CCCCCC')),
            ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.extend([t, Spacer(1, 10)])

    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if s.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = lines[i].strip().strip('|').split('|')
                if not all(re.fullmatch(r'\s*[-:]+\s*', c) for c in cells):
                    rows.append(cells)
                i += 1
            add_table(rows)
            continue
        if s.startswith('# '):
            story.append(para(s[2:], 'TitleCJK'))
        elif s.startswith('## '):
            story.append(para(s[3:], 'H1CJK'))
        elif s.startswith('### '):
            story.append(para(s[4:], 'H2CJK'))
        else:
            story.append(para(s))
        i += 1

    captions = {
        '01': '结构性图。展示三个客户端、应用模块及共同事务数据库，说明模块调用而非界面直接写库。',
        '02': '结构性图（必画类图）。重点查看基数、订单逐夜组成、房型日历联合唯一和请求键唯一约束。',
        '03': '结构性图。应用服务依赖策略、库存与价格服务以及Repository接口，统一事务边界。',
        '04': '行为性图。显示游客、顾客、酒店工作人员、管理员的不同操作范围及系统任务。',
        '05': '行为性图。包含八种状态、合法触发者与库存效果，未确认的超时竞争边界保持明确。',
        '06': '行为性图。覆盖正常提交、参数非法、无结果、重复请求、价格变化和整体回滚。',
        '07': '交互性图。顺序展示权限、幂等、数据库锁、报价与库存重查、原子提交和失败分支。',
        '08': '交互性图。新旧住宿夜并集锁定，按净变化处理重叠夜；失败保持原订单。',
        '09': '结构性图。浏览器、代理、应用、数据库、隔离备份与恢复验证环境。',
    }
    for path in sorted((PACKAGE / 'UML').glob('*.png')):
        w, h = PILImage.open(path).size
        tpl = 'wide' if w / h > 1.25 else 'diagram'
        size = sizes[tpl]
        story.extend([NextPageTemplate(tpl), PageBreak(), para('图版 ' + path.stem.replace('_', ' · '), 'H1CJK'), para(captions[path.name[:2]], 'CaptionCJK')])
        availw, availh = size[0] - 2 * margin, size[1] - 82 * mm
        scale = min(availw / w, availh / h)
        story.append(Image(str(path), width=w * scale, height=h * scale, hAlign='CENTER'))
    manifest = json.loads((SOURCE / 'ui_manifest.json').read_text(encoding='utf-8'))
    for p in manifest:
        tpl = 'text' if p['key'] == '16' else 'ui'
        size = sizes[tpl]
        story.extend([NextPageTemplate(tpl), PageBreak(), para('UI-' + p['key'] + ' · ' + p['title'], 'H1CJK'), para(p['role'] + ' ｜ ' + p['req'] + '。' + p['subtitle'], 'CaptionCJK')])
        path = PACKAGE / 'UI界面' / p['image']
        w, h = PILImage.open(path).size
        scale = min((size[0] - 2 * margin) / w, (size[1] - 82 * mm) / h)
        story.append(Image(str(path), width=w * scale, height=h * scale, hAlign='CENTER'))
    doc.build(story)
    print('PDF:', dest.name, f'{dest.stat().st_size:,} bytes')


def pack():
    target = ROOT / (PACKAGE.name + '.zip')
    files = sorted(p for p in PACKAGE.rglob('*') if p.is_file())
    allowed = {'.pdf', '.png', '.puml'}
    if len(files) != 35 or any(p.suffix not in allowed for p in files):
        raise RuntimeError('Unexpected submission contents: ' + str(len(files)))
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(target) as z:
        for p in files:
            assert z.read(p.relative_to(ROOT).as_posix()) == p.read_bytes()
    print('ZIP:', target.name, '35 files, byte-for-byte verified')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plantuml', type=Path, default=Path(r'C:\Users\11690\AppData\Local\Temp\opencode\plantuml-1.2024.8.jar'))
    parser.add_argument('--pdf-only', action='store_true')
    args = parser.parse_args()
    if not args.pdf_only:
        render_uml(args.plantuml)
        ui_design.build_boards()
        ui_design.exports()
    make_pdf()
    pack()


if __name__ == '__main__':
    main()
