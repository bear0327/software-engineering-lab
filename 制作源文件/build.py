"""Reproducibly build PlantUML, UI boards, plain report and exact submission ZIP."""
from __future__ import annotations
import argparse
import html
import json
import re
import subprocess
import zipfile
from pathlib import Path
from PIL import Image as PILImage
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, A3, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, NextPageTemplate
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
    # A plain coursework layout: one regular Song typeface, no display/bold font.
    pdfmetrics.registerFont(TTFont('CJK', r'C:\Windows\Fonts\simsun.ttc'))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='BodyCJK', fontName='CJK', fontSize=11, leading=18, firstLineIndent=22, wordWrap='CJK', spaceAfter=6))
    styles.add(ParagraphStyle(name='TitleCJK', fontName='CJK', fontSize=16, leading=25, alignment=TA_CENTER, spaceAfter=16))
    styles.add(ParagraphStyle(name='MetaCJK', fontName='CJK', fontSize=11, leading=19, alignment=TA_CENTER, spaceAfter=7))
    styles.add(ParagraphStyle(name='H1CJK', fontName='CJK', fontSize=13, leading=21, spaceBefore=12, spaceAfter=7, keepWithNext=True))
    styles.add(ParagraphStyle(name='H2CJK', fontName='CJK', fontSize=11.5, leading=19, spaceBefore=8, spaceAfter=5, keepWithNext=True))
    styles.add(ParagraphStyle(name='TableCJK', fontName='CJK', fontSize=9.5, leading=15, wordWrap='CJK'))
    styles.add(ParagraphStyle(name='TableHeadCJK', parent=styles['TableCJK']))
    styles.add(ParagraphStyle(name='CaptionCJK', fontName='CJK', fontSize=10.5, leading=17, spaceAfter=10))
    dest = PACKAGE / '实验报告.pdf'
    margin = 19 * mm

    def decorate(c, doc):
        w, h = doc.pagesize
        c.saveState()
        c.setFillColor(colors.black)
        c.setFont('CJK', 9)
        c.drawCentredString(w / 2, 10 * mm, str(doc.page))
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
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LINEABOVE', (0, 0), (-1, 0), .45, colors.black),
            ('LINEBELOW', (0, 0), (-1, 0), .45, colors.black),
            ('LINEBELOW', (0, 1), (-1, -1), .25, colors.black),
            ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
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
        elif i < 7:
            story.append(para(s, 'MetaCJK'))
        else:
            story.append(para(s))
        i += 1

    captions = {
        '01': '结构性图。逻辑关系：三个客户端调用各业务模块，再访问数据库。设计原因：订单和库存需要一起更新，放在同一应用和事务中处理。',
        '02': '结构性图。逻辑关系：一笔订单有多条逐夜记录，每晚关联对应的房型日历。设计原因：连住时需要按天检查房量，并保留下单时的逐夜价格。',
        '03': '结构性图。逻辑关系：BookingService调用权限、状态、库存和数据访问接口，定时任务也从这里处理订单。设计原因：不同入口共用一套业务检查。',
        '04': '行为性图。逻辑关系：游客、顾客、酒店人员和管理员分别关联自己的功能。设计原因：限制数据和操作范围，顾客只管理本人订单，酒店人员只处理本酒店业务。',
        '05': '行为性图。逻辑关系：订单按确认、入住、退房及异常处理进入不同状态。设计原因：每次操作要有明确前提，已取消等终态不能再次入住。',
        '06': '行为性图。流程从输入查询条件到提交结果，包含无房、改价和失败分支。这样可以同时说明正常预订和出错后如何返回提示、撤销修改。',
        '07': '交互性图。调用关系：页面提交后，服务检查请求、价格和库存，再提交订单及各晚预留。设计原因：防止重复建单和只占用部分住宿夜。',
        '08': '交互性图。调用关系：锁定原订单，检查新旧日期并更新占用。设计原因：保留重叠夜原有房量，新日期无房时不影响原订单。',
        '09': '结构性图。测试时应用与数据库同机运行，压测端独立，备份使用隔离存储。这样可以固定测试条件，恢复演练也不会覆盖正在使用的数据。',
    }
    for path in sorted((PACKAGE / 'UML').glob('*.png')):
        w, h = PILImage.open(path).size
        tpl = 'wide' if w / h > 1.25 else 'diagram'
        size = sizes[tpl]
        story.extend([NextPageTemplate(tpl), PageBreak(), para('图' + str(int(path.name[:2])) + ' ' + path.stem.split('_', 1)[1], 'H1CJK'), para(captions[path.name[:2]], 'CaptionCJK')])
        availw, availh = size[0] - 2 * margin, size[1] - 82 * mm
        scale = min(availw / w, availh / h)
        story.append(Image(str(path), width=w * scale, height=h * scale, hAlign='CENTER'))
    manifest = json.loads((SOURCE / 'ui_manifest.json').read_text(encoding='utf-8'))
    for p in manifest:
        tpl = 'text' if p['key'] == '16' else 'ui'
        size = sizes[tpl]
        story.extend([NextPageTemplate(tpl), PageBreak(), para('UI-' + p['key'] + ' ' + p['title'], 'H1CJK'), para(p['role'] + '，对应' + p['req'] + '。' + p['subtitle'], 'CaptionCJK')])
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
