"""Shared vector UI model -> editable draw.io, SVG, PNG, and HTML prototype.

The exported diagrams.net document contains individual shape/text cells.
PNG/SVG use the same geometry rather than independently recreated layouts.
"""
from __future__ import annotations
import html
import json
import textwrap
from pathlib import Path
from xml.etree import ElementTree as ET
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '制作源文件'
OUTPUT = ROOT / '实验2_241820122_商世雄' / 'UI界面'
INK = '#172B3A'
TEAL = '#087F82'
MUTED = '#667C89'
LINE = '#DCE5E9'
BG = '#F3F6F7'
WHITE = '#FFFFFF'
GOLD = '#B47835'
RED = '#B64D46'
BOARDS = []


class Board:
    def __init__(self, key, title, role, subtitle, req, mobile=False):
        self.key, self.title, self.role, self.subtitle, self.req = key, title, role, subtitle, req
        self.w, self.h = (390, 844) if mobile else (1440, 1000)
        self.nodes, self.actions, self.fields = [], [], []
        self.rect(0, 0, self.w, self.h, BG)
        BOARDS.append(self)
        if mobile:
            return
        self.rect(0, 0, 220, 1000, INK)
        self.text(27, 32, '泊岸 / STAY', 24, WHITE, bold=True)
        self.text(28, 70, '酒店预订系统 · 设计原型', 12, '#A9BEC9')
        self.text(28, 135, role, 14, '#7AD5D0', bold=True)
        menu = {
            '顾客端': [('02', '酒店与空房'), ('05', '我的订单'), ('01', '账号与登录')],
            '酒店工作台': [('08', '房型资料'), ('09', '每日库存与价格'), ('10', '预订确认与拒绝'), ('11', '入住与退房'), ('14', '业务统计'), ('15', '操作日志')],
            '平台管理台': [('12', '酒店审核与启停'), ('13', '工作人员账号'), ('14', '全平台统计'), ('15', '全平台日志')],
        }
        for i, (dest, name) in enumerate(menu.get(role, menu['顾客端'])):
            y = 183 + i * 56
            if dest == key:
                self.rect(16, y - 9, 188, 43, '#294450', radius=8)
                self.rect(16, y - 2, 3, 29, '#6ED3C9')
            self.text(29, y, name, 15, WHITE if dest == key else '#BACBD3')
            self.actions.append(dict(x=16, y=y - 9, w=188, h=43, action='goto:' + dest, label=name))
        self.text(28, 871, '示例数据 / 无真实支付', 12, '#A9BEC9')
        self.text(28, 895, '数据范围以登录身份为准', 12, '#A9BEC9')
        self.button(26, 934, 166, '切换演示角色', 'role', secondary=True)
        self.rect(220, 0, 1220, 73, WHITE)
        self.text(252, 27, '工作空间   /   ' + title, 14, MUTED)
        self.text(1139, 27, '设计样例  ·  ' + role, 14, INK)
        self.text(254, 105, title, 30, INK, bold=True)
        self.text(254, 151, subtitle, 15, MUTED)
        self.text(254, 967, 'UI-' + key + '  |  ' + req + '   ·   业务校验以服务端为准', 12, MUTED)

    def rect(self, x, y, w, h, fill=WHITE, stroke=None, radius=0):
        self.nodes.append(dict(kind='rect', x=x, y=y, w=w, h=h, fill=fill, stroke=stroke, radius=radius))

    def text(self, x, y, text, size=16, color=INK, bold=False):
        self.nodes.append(dict(kind='text', x=x, y=y, text=str(text), size=size, color=color, bold=bold))

    def line(self, x, y, w, color=LINE):
        self.rect(x, y, w, 1, color)

    def card(self, x, y, w, h, title=None):
        self.rect(x, y, w, h, WHITE, LINE, 12)
        if title:
            self.text(x + 24, y + 24, title, 19, INK, True)

    def button(self, x, y, w, label, action='message', secondary=False, danger=False):
        fill = '#FFF3F0' if danger else (WHITE if secondary else TEAL)
        color = RED if danger else (TEAL if secondary else WHITE)
        self.rect(x, y, w, 42, fill, LINE if secondary else None, 7)
        tw = ImageDraw.Draw(Image.new('RGB', (1, 1))).textlength(label, font=font(15))
        self.text(x + max(12, (w - tw) / 2), y + 11, label, 15, color)
        self.actions.append(dict(x=x, y=y, w=w, h=42, action=action, label=label))

    def badge(self, x, y, label, tone='teal'):
        color, fill = {'teal': (TEAL, '#E8F5F2'), 'gold': (GOLD, '#FFF3E3'), 'red': (RED, '#FFF0EC'), 'gray': (MUTED, '#EDF1F3')}[tone]
        w = 24 + len(label) * 14
        self.rect(x, y, w, 28, fill, radius=6)
        self.text(x + 12, y + 6, label, 13, color)

    def field(self, x, y, w, label, value, name=None, choices=None):
        self.text(x, y, label, 13, MUTED)
        self.rect(x, y + 27, w, 45, WHITE, LINE, 7)
        self.text(x + 13, y + 41, value, 15)
        if name:
            self.fields.append(dict(x=x, y=y + 27, w=w, h=45, value=value, name=name, choices=choices))

    def banner(self, y, title, detail='', tone='teal'):
        fill, color = ('#FFF4E6', GOLD) if tone == 'gold' else ('#E8F5F2', TEAL)
        self.rect(254, y, 1152, 75, fill, radius=9)
        self.text(274, y + 13, title, 15, color, True)
        self.text(274, y + 43, detail, 13, color)

    def table(self, x, y, widths, headers, rows, rowh=60):
        total = sum(widths)
        self.rect(x, y, total, 42, '#EFF4F5', radius=3)
        px = x
        for w, t in zip(widths, headers):
            self.text(px + 14, y + 13, t, 13, MUTED)
            px += w
        for i, row in enumerate(rows):
            py = y + 42 + i * rowh
            px = x
            for w, t in zip(widths, row):
                self.text(px + 14, py + 19, t, 14)
                px += w
            self.line(x, py + rowh - 1, total)


def font(size, bold=False):
    return ImageFont.truetype(r'C:\Windows\Fonts\msyhbd.ttc' if bold else r'C:\Windows\Fonts\msyh.ttc', round(size))


def build_boards():
    b = Board('01', '账号登录与注册', '顾客端', '顾客自行注册；酒店工作人员账号由平台管理员创建。', 'REQ-001 / 023')
    b.card(254, 202, 596, 690)
    b.rect(278, 226, 548, 214, '#E8F1EF', radius=9)
    for x, height in [(325, 115), (413, 160), (514, 130), (614, 177), (713, 111)]:
        b.rect(x, 421 - height, 66, height, '#C2D8D3', radius=3)
        for yy in range(430 - height, 401, 26):
            b.rect(x + 15, yy, 11, 12, '#F4F9F6')
            b.rect(x + 41, yy, 11, 12, '#F4F9F6')
    b.text(289, 471, '把每一晚安排妥当', 28, INK, True)
    for i, s in enumerate(['全程有房再预订，按入住夜准确计价。', '订单状态和处理结果清晰可查。', '不接入在线支付，住宿费用线下结算。']):
        b.text(289, 536 + i * 46, s, 18, MUTED)
    b.badge(289, 730, '三类身份 · 各自授权')
    b.card(878, 202, 528, 690, '欢迎登录')
    b.field(908, 281, 466, '账号', 'customer@example.com', 'account')
    b.field(908, 378, 466, '密码', '••••••••', 'password')
    b.field(908, 475, 466, '登录身份', '顾客', 'role', ['顾客', '酒店工作人员', '平台管理员'])
    b.button(908, 584, 466, '登录', 'login')
    b.button(908, 645, 466, '注册顾客账号', 'register', True)
    b.text(908, 732, '密码仅作原型演示，不进行真实认证。', 14, MUTED)
    b.text(908, 765, '真实系统使用加盐单向哈希和服务端权限校验。', 13, MUTED)

    b = Board('02', '寻找下一段旅程的落脚处', '顾客端', '按城市、日期、人数、房型和整段住宿价格组合查询。', 'REQ-004 / 007')
    b.card(254, 200, 1152, 181)
    for x, w, label, val, name in [(278, 160, '目的城市', '南京', 'city'), (454, 187, '入住日期', '2026-11-10', 'checkIn'), (657, 187, '离店日期', '2026-11-12', 'checkOut'), (860, 133, '房间 / 人数', '1 间 / 2 人', 'occupancy'), (1009, 196, '每间整段价格', '¥ 0 — 1,000', 'price')]:
        b.field(x, 224, w, label, val, name)
    b.button(1224, 251, 154, '查询空房', 'search')
    b.text(278, 330, '房型：不限 / 大床 / 双床      价格按一间房整个入住区间筛选，不按单晚价筛选。', 14, MUTED)
    b.text(254, 409, '符合条件的可订房型', 21, INK, True)
    b.text(1111, 415, '南京  ·  2晚  ·  1间2人', 14, MUTED)
    for i, (name, area, room, price) in enumerate([('南京泊岸酒店', '鼓楼区 · 湖南路 18 号', '舒适大床房', '¥ 658'), ('秦淮栖居酒店', '秦淮区 · 白鹭街 29 号', '城景双床房', '¥ 726')]):
        y = 456 + i * 222
        b.card(254, y, 1152, 202)
        b.rect(274, y + 20, 199, 161, '#DBEAE5', radius=8)
        b.rect(308, y + 52, 121, 116, '#A8C7BC', radius=4)
        b.rect(351, y + 100, 34, 68, '#F5F8EF')
        b.text(498, y + 25, name, 23, INK, True)
        b.text(498, y + 65, area, 14, MUTED)
        b.text(498, y + 105, room + '  ·  可住2人  ·  全程可订', 16)
        b.badge(498, y + 144, '逐夜明细可查')
        b.text(1172, y + 42, price, 29, TEAL, True)
        b.text(1172, y + 86, '每间 / 2晚总价', 13, MUTED)
        b.button(1172, y + 124, 208, '查看房型', 'goto:03')
    b.text(254, 923, '无结果时显示“暂无符合条件的可订房型”；非法日期定位字段提示。', 13, MUTED)

    b = Board('03', '南京泊岸酒店', '顾客端', '南京市鼓楼区湖南路18号  ·  联系电话 025-8000-1234', 'REQ-002 / 003 / 004')
    b.card(254, 204, 1152, 180, '舒适、清晰、可确定的入住安排')
    b.badge(278, 267, '营业中')
    b.text(430, 272, '只管理房型数量，不指定具体房间号。', 17)
    b.text(278, 329, '入住 2026-11-10   →   离店 2026-11-12     2晚 / 1间 / 2人', 17)
    b.card(254, 411, 1152, 439, '可订房型')
    b.table(278, 476, [270, 160, 180, 220, 272], ['房型', '入住容量', '11月10日', '11月11日', '每间2晚总价'], [['舒适大床房', '2人 / 间', '¥ 299 / 余3', '¥ 359 / 余1', '¥ 658'], ['城景双床房', '2人 / 间', '¥ 329 / 余2', '¥ 399 / 余2', '¥ 728']])
    b.button(1069, 671, 283, '预订舒适大床房', 'goto:04')
    b.text(279, 697, '全程逐夜满足库存且无停售才允许预订。', 15, MUTED)
    b.text(279, 762, '费用线下结算。订单生成后保存成交快照，后续酒店调价不倒改订单。', 15, MUTED)

    b = Board('04', '填写并提交预订', '顾客端', '提交成功即预留全程库存，等待本酒店工作人员确认。', 'REQ-005 / 006 / 007 / 008')
    b.card(254, 201, 720, 707, '入住资料')
    b.text(278, 272, '南京泊岸酒店  ·  舒适大床房', 20, INK, True)
    b.text(278, 317, '11月10日入住 → 11月12日离店   /   共2晚', 17)
    b.field(278, 379, 312, '房间数量', '1', 'rooms')
    b.field(614, 379, 332, '入住人数', '2', 'guests')
    b.field(278, 482, 668, '联系人', '商同学', 'contact')
    b.field(278, 586, 668, '联系电话', '13800138000', 'phone')
    b.text(278, 703, '提交表示接受右侧本次逐夜报价。', 15, MUTED)
    b.text(278, 744, '报价变化时先重新确认；无房时整体失败，不留下部分占用。', 14, MUTED)
    b.card(997, 201, 409, 707, '本次价格明细')
    b.table(1021, 278, [180, 180], ['住宿夜', '单间单价'], [['11月10日', '¥ 299'], ['11月11日', '¥ 359']])
    b.line(1021, 486, 359)
    b.text(1021, 520, '2晚 × 1间', 16, MUTED)
    b.text(1021, 564, '¥ 658', 38, TEAL, True)
    b.badge(1021, 638, '不含离店当晚')
    b.button(1021, 717, 359, '确认报价并提交', 'create')
    b.button(1021, 779, 359, '演示提交前价格变化', 'reprice', True)

    b = Board('05', '我的订单', '顾客端', '仅展示本人订单；待确认可改期，已确认只允许修改联系人。', 'REQ-008 / 011 / 012 / 016')
    b.banner(201, '待确认订单保留30分钟', '成功修改待确认订单后重新计时；准确截止规则仍需业务确认。', 'gold')
    b.card(254, 303, 1152, 554)
    b.text(278, 331, '全部订单     待确认     已确认     已入住     已结束', 17)
    b.table(278, 395, [222, 270, 218, 128, 132, 132], ['订单编号', '酒店 / 房型', '入住 — 离店', '间数 / 夜数', '成交总价', '当前状态'], [['HB261106001', '泊岸 · 舒适大床房', '11-10 — 11-12', '1间 / 2晚', '¥ 658', '待确认'], ['HB261105006', '泊岸 · 城景双床房', '11-15 — 11-17', '1间 / 2晚', '¥ 728', '已确认'], ['HB261101018', '秦淮 · 大床房', '11-01 — 11-03', '1间 / 2晚', '¥ 598', '已退房']])
    b.button(278, 682, 172, '查看第一笔详情', 'goto:07')
    b.button(469, 682, 172, '修改待确认订单', 'goto:06', True)
    b.text(278, 775, '已取消、已拒绝、已超时、未入住和已退房均不可重新入住。', 15, MUTED)

    b = Board('06', '修改待确认订单', '顾客端', '新日期无房时保留原订单；先核价，成功后一次性处理新旧预留。', 'REQ-006 / 007 / 011')
    b.card(254, 203, 550, 651, '原订单 · HB261106001')
    for i, (a, v) in enumerate([('房型', '舒适大床房'), ('入住 / 离店', '11月10日 → 11月12日'), ('间数 / 人数', '1间 / 2人'), ('价格快照', '¥299 + ¥359 = ¥658'), ('当前状态', '待确认')]):
        b.text(278, 284 + i * 75, a, 14, MUTED)
        b.text(460, 283 + i * 75, v, 16)
    b.badge(278, 729, '修改失败不影响原单')
    b.card(828, 203, 578, 651, '新入住方案')
    b.field(852, 280, 248, '新入住日期', '2026-11-10', 'newIn')
    b.field(1124, 280, 254, '新离店日期', '2026-11-11', 'newOut')
    b.field(852, 383, 526, '新房型 / 间数', '舒适大床房 / 1间', 'newRoom')
    b.text(852, 499, '新总价  ¥ 299', 28, TEAL, True)
    b.text(852, 553, '10日保留原占用，11日释放1间。', 16)
    b.text(852, 594, '不把自己的原预留误判成他人占用。', 15, MUTED)
    b.button(852, 658, 526, '接受新报价并保存', 'modify')
    b.button(852, 720, 526, '演示新日期无房：原单保留', 'modifyFail', True)

    b = Board('07', '订单详情与操作历史', '顾客端', 'HB261106001  ·  服务端版本 v3  ·  当前状态和操作结果以最新数据为准', 'REQ-008 / 012 / 016 / 019')
    b.banner(201, '待确认 · 已预留全程房量', '示例订单：入住11月10日、离店11月12日；酒店确认不再重复扣减库存。')
    b.card(254, 300, 718, 601, '预订信息')
    b.table(278, 373, [230, 436], ['信息项', '内容'], [['酒店 / 房型', '南京泊岸酒店 / 舒适大床房'], ['住宿区间', '2026-11-10 → 2026-11-12（2晚）'], ['房量 / 人数', '1间 / 2人'], ['联系人', '商同学 / 138****8000'], ['逐夜成交价', '11-10 ¥299；11-11 ¥359'], ['成交总价', '¥658（后续酒店调价不影响本单）']], 57)
    b.card(996, 300, 410, 601, '可执行操作')
    b.button(1020, 375, 362, '修改待确认订单', 'goto:06')
    b.button(1020, 439, 362, '取消本人订单', 'cancel', danger=True)
    b.text(1020, 518, '已确认取消截止：入住日当地18:00前。', 13, MUTED)
    b.text(1020, 555, '已入住不能直接取消；不处理退款。', 14, MUTED)
    b.line(1020, 604, 362)
    b.text(1020, 634, '操作历史', 18, INK, True)
    b.text(1020, 683, '14:00  顾客提交 / 待确认 / 成功', 14)
    b.text(1020, 724, '14:01  相同请求重试 / 返回原结果', 14)
    b.text(1020, 775, '日志只读；仅查看本人订单。', 14, MUTED)

    b = Board('08', '房型资料管理', '酒店工作台', '当前酒店：南京泊岸酒店  ·  仅维护本酒店，不管理具体房间号。', 'REQ-001 / 003')
    b.card(254, 204, 1152, 660, '房型清单')
    b.table(278, 280, [180, 268, 172, 180, 302], ['房型编号', '房型名称', '单间可住人数', '房间总数', '说明'], [['RT-1001', '舒适大床房', '2人', '10间', '逐日供给不得超过总数'], ['RT-1002', '城景双床房', '2人', '8间', '停售不自动取消已有订单']])
    b.field(278, 504, 345, '房型名称', '舒适大床房', 'roomName')
    b.field(647, 504, 250, '可住人数', '2', 'capacity')
    b.field(921, 504, 249, '房间总数', '10', 'totalRooms')
    b.button(278, 624, 195, '保存房型资料', 'catalogSave')
    b.button(496, 624, 218, '维护逐日价量', 'goto:09', True)
    b.text(278, 726, '减少房间总数时，需确保仍覆盖相关住宿日供给与已有占用；不删除订单引用。', 15, MUTED)

    b = Board('09', '每日库存、价格与停售', '酒店工作台', '房型 RT-1001 · 舒适大床房   |   分清供给总量、已占用与剩余量。', 'REQ-003 / 006 / 007 / 017')
    b.banner(202, '剩余房量 = 当日供给总量 − 仍应占用的房量', '已预留的订单不会因为酒店调价而改变价格；停售只阻止新预订。')
    b.card(254, 304, 1152, 567)
    b.table(278, 334, [170, 170, 160, 160, 160, 282], ['住宿日期', '供给总量', '已占用', '剩余', '单晚价格', '销售状态'], [['2026-11-10', '3间', '2间', '1间', '¥ 299', '可售'], ['2026-11-11', '1间', '0间', '1间', '¥ 359', '可售'], ['2026-11-12', '3间', '1间', '2间', '¥ 329', '停售']])
    b.field(278, 615, 242, '11月10日供给总量', '3', 'supply')
    b.field(544, 615, 242, '11月10日单晚价格', '299', 'nightPrice')
    b.field(810, 615, 242, '销售状态', '可售', 'sales', ['可售', '停售'])
    b.button(1076, 642, 302, '保存当日变更', 'calendarSave')
    b.text(278, 756, '示例：总量3、占用2，还能再售1间；若把总量调成1，必须拒绝，不能负库存。', 15, MUTED)

    b = Board('10', '预订确认与拒绝', '酒店工作台', '按本酒店、当前状态与版本处理；其他酒店订单不可访问。', 'REQ-009 / 010 / 016')
    b.banner(202, '待确认订单 1 笔', '30分钟到期但超时任务尚未提交的竞争规则待确认；本设计不擅自定为已确认策略。', 'gold')
    b.card(254, 305, 1152, 547, '订单 HB261106001')
    b.table(278, 381, [222, 220, 180, 180, 300], ['顾客联系人', '住宿日期', '房型 / 间数', '成交总价', '当前状态'], [['商同学 / 138****8000', '11-10 → 11-12', '大床房 / 1间', '¥ 658', '待确认 · v3']])
    b.text(278, 525, '提交时全程房量已预留；确认只改变状态，不再扣减。', 18)
    b.field(278, 584, 708, '拒绝原因（拒绝时填写）', '无法满足特殊接待条件', 'rejectReason')
    b.button(278, 708, 224, '确认该预订', 'confirm')
    b.button(526, 708, 224, '拒绝并释放预留', 'reject', danger=True)
    b.button(774, 708, 224, '刷新当前状态', 'refresh', True)

    b = Board('11', '现场入住与正常退房', '酒店工作台', '核对订单和顾客身份，系统只记录核验结果，不保存身份证照片。', 'REQ-013 / 014 / 015 / 016')
    b.card(254, 202, 1152, 176)
    b.field(278, 226, 715, '订单编号 / 联系方式', 'HB261110016', 'stayOrder')
    b.button(1017, 253, 361, '查找本酒店订单', 'lookup')
    b.card(254, 405, 1152, 469, '入住核验')
    b.badge(1180, 426, '已确认')
    b.table(278, 490, [250, 250, 250, 352], ['订单编号', '计划住宿日期', '房型 / 数量', '核验结果'], [['HB261110016', '11-10 → 11-12', '舒适大床房 / 1间', '现场人工核对通过']])
    b.text(278, 632, '办理入住须符合入住日期；已取消、已拒绝、已超时、未入住不能入住。', 16)
    b.button(278, 710, 237, '记录核验并办理入住', 'checkin')
    b.button(538, 710, 237, '已入住订单正常退房', 'checkout', True)
    b.text(278, 803, '重复操作不产生第二次效果。正常退房不把已经消费的住宿夜恢复为可售。', 15, MUTED)

    b = Board('12', '酒店审核、启停与异常处置', '平台管理台', '停业阻止新预订；已有订单分类处理，不能抹去历史记录。', 'REQ-002 / 017 / 019')
    b.card(254, 204, 1152, 274, '酒店管理')
    b.table(278, 277, [210, 270, 160, 160, 302], ['酒店编号', '酒店名称', '城市', '当前状态', '审核信息'], [['HT-1001', '南京泊岸酒店', '南京', '营业中', '审核通过 / 2位工作人员'], ['HT-1002', '秦淮栖居酒店', '南京', '待审核', '资料待核对']])
    b.card(254, 503, 1152, 405, '停业影响预览 · 南京泊岸酒店')
    b.text(278, 568, '待确认 1笔   /   已确认 1笔   /   已入住 1笔', 20, INK, True)
    b.field(278, 624, 708, '处理原因（必填）', '酒店临时停业检修', 'closureReason')
    b.button(1010, 651, 368, '标记停业，停止新预订', 'closeHotel', danger=True)
    b.text(278, 731, '待确认 / 已确认：管理员逐单取消，释放未消费预留，并记录通知待办。', 15)
    b.text(278, 771, '已入住：保留当前状态，由酒店与平台人工协调，不直接变为已退房。', 15)
    b.button(278, 827, 188, '逐单处理异常', 'handleException', True)
    b.button(486, 827, 188, '审核通过酒店', 'approveHotel', True)
    b.button(694, 827, 188, '手动恢复营业', 'openHotel', True)
    b.text(916, 842, '通知状态：待处理 / 已通知 / 重试', 13, MUTED)

    b = Board('13', '工作人员账号管理', '平台管理台', '每名工作人员绑定唯一酒店；停用账号不删除历史操作记录。', 'REQ-001 / 020 / 023')
    b.card(254, 204, 1152, 657, '工作人员账号')
    b.table(278, 278, [230, 210, 310, 160, 192], ['账号', '姓名', '唯一所属酒店', '状态', '权限范围'], [['staff-001', '王前台', 'HT-1001 南京泊岸酒店', '启用', '仅本酒店'], ['staff-002', '李前台', 'HT-1002 秦淮栖居酒店', '停用', '禁止业务操作']])
    b.field(278, 506, 337, '账号', 'staff-003', 'staffAccount')
    b.field(639, 506, 337, '姓名', '陈前台', 'staffName')
    b.field(1000, 506, 378, '所属酒店（唯一）', 'HT-1001 南京泊岸酒店', 'staffHotel')
    b.button(278, 635, 222, '创建工作人员账号', 'createStaff')
    b.button(524, 635, 222, '停用选中账号', 'disableStaff', danger=True)
    b.text(278, 751, '酒店人员不能自建管理员或跨酒店授权；平台管理员不能代替顾客正常下单。', 15, MUTED)

    b = Board('14', '预订数量与间夜统计', '酒店工作台', '工作人员限本酒店，管理员可切换全平台；不统计收入或入住率。', 'REQ-018 / 001')
    b.card(254, 204, 1152, 151)
    b.field(278, 226, 252, '计划入住日从', '2026-11-01', 'statStart')
    b.field(554, 226, 252, '至', '2026-11-30', 'statEnd')
    b.field(830, 226, 285, '房型', '全部房型', 'statRoom')
    b.button(1139, 253, 239, '汇总', 'stats')
    for x, title, value, sub in [(254, '有效预订数', '3 笔', '已确认 / 已入住 / 已退房'), (840, '已预订间夜数', '9 间夜', '每单间数 × 计划住宿夜数')]:
        b.card(x, 383, 566, 185)
        b.text(x + 24, 406, title, 16, MUTED)
        b.text(x + 24, 449, value, 38, TEAL, True)
        b.text(x + 24, 519, sub, 14, MUTED)
    b.card(254, 594, 1152, 281, '计算明细')
    b.table(278, 656, [250, 250, 250, 352], ['状态', '订单数', '间数 × 夜数', '间夜贡献'], [['已确认', '1', '2 × 3', '6'], ['已入住', '1', '1 × 1', '1'], ['已退房', '1', '1 × 2', '2']], 47)
    b.text(254, 913, '按计划入住日归入区间，非逐夜分摊；日期端点仍待约定，界面应明确显示最终口径。', 14, MUTED)

    b = Board('15', '操作日志与追踪', '酒店工作台', '日志只读、保留180天；管理员查全平台，酒店人员只查本酒店。', 'REQ-019 / 023 / 024')
    b.card(254, 205, 1152, 152)
    b.field(278, 228, 240, '操作者', '全部', 'logActor')
    b.field(542, 228, 332, '时间范围', '2026-11-06 00:00 — 23:59', 'logTime')
    b.field(898, 228, 236, '操作类型', '全部', 'logType')
    b.button(1158, 255, 220, '查询日志', 'logs')
    b.card(254, 383, 1152, 509, '关键操作记录（脱敏）')
    b.table(278, 451, [130, 148, 180, 140, 240, 264], ['时间', '操作者', '对象编号', '动作', '前后状态 / 结果', '原因'], [['14:00:12', '顾客 C-001', 'HB261106001', '提交预订', '无 → 待确认 / 成功', '联系人 138****8000'], ['14:01:32', 'staff-001', 'HB261106001', '确认预订', '待确认 → 已确认', '本酒店确认'], ['14:02:01', 'staff-001', 'RT-1001/11-10', '调减供给', '拒绝 / 数据未变', '新总量不足覆盖占用'], ['14:03:04', '系统任务', 'HB261106020', '超时处理', '待确认 → 已超时', '到期释放一次']])
    b.text(278, 781, '日志与订单历史均按身份和对象归属过滤；页面与接口都不提供改写日志功能。', 15, MUTED)
    b.text(278, 821, '失败请求另记安全审计；成功状态、库存和业务审计在同一事务提交。', 15, MUTED)

    b = Board('16', '移动端订单详情', '顾客端', '手机关键任务适配', 'REQ-025', mobile=True)
    b.rect(0, 0, 390, 85, INK)
    b.text(20, 17, '09:41', 13, WHITE)
    b.text(20, 48, '‹  我的订单', 19, WHITE, True)
    b.text(20, 111, '等待酒店确认', 25, INK, True)
    b.text(20, 151, '订单号 HB261106001', 13, MUTED)
    b.card(16, 193, 358, 240)
    b.text(34, 216, '南京泊岸酒店', 20, INK, True)
    b.text(34, 254, '舒适大床房  /  1间  /  2人', 14)
    b.line(34, 291, 322)
    b.text(34, 310, '11月10日', 22, TEAL, True)
    b.text(232, 310, '11月12日', 22, TEAL, True)
    b.text(34, 348, '入住', 13, MUTED)
    b.text(232, 348, '离店 · 共2晚', 13, MUTED)
    b.text(34, 389, '联系人 商同学 / 138****8000', 14)
    b.card(16, 450, 358, 203)
    b.text(34, 472, '逐夜成交明细', 17, INK, True)
    b.text(34, 516, '11月10日  ¥299    /    11月11日  ¥359', 13)
    b.line(34, 550, 322)
    b.text(34, 578, '总价', 15)
    b.text(246, 566, '¥ 658', 29, TEAL, True)
    b.text(20, 678, '取消、修改均重新检查当前状态和版本。', 13, MUTED)
    b.button(16, 738, 172, '修改预订', 'goto:06', True)
    b.button(202, 738, 172, '取消订单', 'cancel', danger=True)
    b.text(20, 809, '手机原型 · 不是真实业务操作', 11, MUTED)


def exports():
    SOURCE.mkdir(exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    mx = ET.Element('mxfile', host='app.diagrams.net', agent='LAB2 vector UI generator', version='24.7.17')
    manifest = []
    for b in BOARDS:
        im = Image.new('RGB', (b.w * 2, b.h * 2), WHITE)
        draw = ImageDraw.Draw(im)
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{b.w}" height="{b.h}" viewBox="0 0 {b.w} {b.h}">']
        svg.append('<style>text{font-family:"Microsoft YaHei",sans-serif;dominant-baseline:text-before-edge}</style>')
        diag = ET.SubElement(mx, 'diagram', id='ui-' + b.key, name='UI-' + b.key + ' ' + b.title)
        model = ET.SubElement(diag, 'mxGraphModel', dx='1440', dy='1000', grid='1', gridSize='10', page='1', pageWidth=str(b.w), pageHeight=str(b.h))
        root = ET.SubElement(model, 'root')
        ET.SubElement(root, 'mxCell', id='0')
        ET.SubElement(root, 'mxCell', id='1', parent='0')
        for i, n in enumerate(b.nodes):
            ident = str(i + 2)
            if n['kind'] == 'rect':
                x, y, w, h = (n[k] for k in ['x', 'y', 'w', 'h'])
                coords = [round(v * 2) for v in [x, y, x + w, y + h]]
                draw.rounded_rectangle(coords, radius=n['radius'] * 2, fill=n['fill'], outline=n['stroke'], width=2)
                svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{n["radius"]}" fill="{n["fill"]}" stroke="{n["stroke"] or "none"}"/>')
                style = f'rounded={int(n["radius"] > 0)};whiteSpace=wrap;html=0;fillColor={n["fill"]};strokeColor={n["stroke"] or "none"};arcSize=12;'
                cell = ET.SubElement(root, 'mxCell', id=ident, value='', style=style, vertex='1', parent='1')
            else:
                x, y, text, size = n['x'], n['y'], n['text'], n['size']
                ft = font(size * 2, n['bold'])
                draw.text((round(x * 2), round(y * 2)), text, font=ft, fill=n['color'], anchor='lt')
                w = draw.textlength(text, font=ft) / 2 + 5
                h = size * 1.5
                svg.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{n["color"]}" font-weight="{700 if n["bold"] else 400}">{html.escape(text)}</text>')
                style = f'text;html=0;align=left;verticalAlign=top;whiteSpace=wrap;overflow=visible;strokeColor=none;fillColor=none;fontFamily=Microsoft YaHei;fontSize={size};fontColor={n["color"]};fontStyle={int(n["bold"])};spacing=0;'
                cell = ET.SubElement(root, 'mxCell', id=ident, value=text, style=style, vertex='1', parent='1')
            ET.SubElement(cell, 'mxGeometry', x=str(x), y=str(y), width=str(w), height=str(h), attrib={'as': 'geometry'})
        svg.append('</svg>')
        filename = 'UI-' + b.key + '_' + b.title
        svg_path = SOURCE / 'UI矢量' / (filename + '.svg')
        svg_path.parent.mkdir(exist_ok=True)
        svg_path.write_text('\n'.join(svg), encoding='utf-8')
        im.save(OUTPUT / (filename + '.png'))
        manifest.append(dict(key=b.key, title=b.title, role=b.role, subtitle=b.subtitle, req=b.req, w=b.w, h=b.h, image=filename + '.png', svg='UI矢量/' + filename + '.svg', actions=b.actions, fields=b.fields, nodes=b.nodes))
    ET.indent(mx)
    ET.ElementTree(mx).write(SOURCE / '酒店预订UI.drawio', encoding='utf-8', xml_declaration=True)
    (SOURCE / 'ui_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    make_prototype(manifest)
    print(f'UI: {len(BOARDS)} editable pages + PNG/SVG + HTML')


def make_prototype(manifest):
    data = json.dumps(manifest, ensure_ascii=False).replace('</', '<\\/')
    document = '''<!DOCTYPE html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>泊岸酒店 · LAB2交互原型</title><style>
*{box-sizing:border-box}body{margin:0;background:#e2e9ec;color:#172b3a;font-family:'Microsoft YaHei',sans-serif}header{padding:12px 20px;background:#fff;border-bottom:1px solid #ccd7dc;display:flex;align-items:center;gap:16px;position:sticky;top:0;z-index:5}select{padding:8px;border:1px solid #ccd7dc;border-radius:5px}#status{font-size:13px;color:#667c89}#viewport{padding:16px;overflow:auto}#canvas{position:relative;margin:auto;background:white;transform-origin:top left}#canvas img{width:100%;height:100%;display:block}#canvas button{position:absolute;border:0;cursor:pointer;background:transparent;color:transparent;border-radius:7px}#canvas button:hover{outline:3px solid #7bc8bd;background:#087f8210}#canvas button:focus-visible{outline:3px solid #087f82}#canvas input,#canvas select{position:absolute;border:1px solid #dce5e9;border-radius:7px;padding:9px 12px;background:white;color:#172b3a;font-size:15px;font-family:inherit}dialog{border:1px solid #dce5e9;border-radius:12px;padding:28px;max-width:560px;line-height:1.8}dialog::backdrop{background:#172b3a66}dialog button{padding:10px 22px;border:0;background:#087f82;color:white;border-radius:6px;cursor:pointer}#message{white-space:pre-line;margin-bottom:22px}#state{font-size:12px;margin-top:16px;color:#667c89}
</style><header><b>泊岸 · 可点击原型</b><select id="pages" aria-label="原型页面"></select><span id="status">演示数据，不连接真实后台。</span><button id="reset">重置演示</button></header><main id="viewport"><div id="canvas"></div></main><dialog id="dialog"><div id="message"></div><button id="close">知道了</button><div id="state"></div></dialog>
<script>const pages=MANIFEST;let current='02';let state={booking:'待确认',version:3,rooms:1,nights:2,total:658,priceChanged:false,hotel:'营业中',stay:'已确认'};const canvas=document.querySelector('#canvas'),selector=document.querySelector('#pages'),dialog=document.querySelector('#dialog');
for(const p of pages){let o=document.createElement('option');o.value=p.key;o.textContent=`UI-${p.key} ${p.title}`;selector.append(o)}
function show(key){current=key;const p=pages.find(p=>p.key===key);selector.value=key;canvas.replaceChildren();canvas.style.width=p.w+'px';canvas.style.height=p.h+'px';let img=new Image();img.src=p.svg;img.alt=p.title;canvas.append(img);for(const a of p.actions){let el=document.createElement('button');el.title=a.label;el.setAttribute('aria-label',a.label);Object.assign(el.style,{left:a.x+'px',top:a.y+'px',width:a.w+'px',height:a.h+'px'});el.onclick=()=>act(a.action);canvas.append(el)}for(const f of p.fields){let el=document.createElement(f.choices?'select':'input');if(f.choices){for(const c of f.choices){let o=document.createElement('option');o.textContent=c;el.append(o)}}else el.value=f.value;if(f.name==='password'){el.type='password';el.value='demo123456'}el.dataset.name=f.name;el.setAttribute('aria-label',f.name);Object.assign(el.style,{left:f.x+'px',top:f.y+'px',width:f.w+'px',height:f.h+'px'});canvas.append(el)}document.querySelector('#status').textContent=`动态演示：订单 ${state.booking} / v${state.version} / ¥${state.total}；酒店 ${state.hotel}。页面底图为固定设计样例。`}
function val(n){return canvas.querySelector(`[data-name="${n}"]`)?.value||''}function msg(s){document.querySelector('#message').textContent=s;document.querySelector('#state').textContent=`动态状态：${state.booking} / 版本${state.version} / ${state.nights}晚 / ¥${state.total}。固定底图不是实时业务数据。`;dialog.showModal();show(current)}
function act(a){if(a.startsWith('goto:'))return show(a.split(':')[1]);switch(a){case'role':return show(current==='12'?'02':current==='10'?'12':'10');case'login':return show(val('role')==='平台管理员'?'12':val('role')==='酒店工作人员'?'10':'02');case'register':return msg('顾客注册演示：真实系统应校验账号唯一性、密码规则并保存加盐哈希。工作人员不能自行注册。');case'search':if(!val('city'))return msg('请填写城市。');if(val('checkOut')<=val('checkIn'))return msg('离店日期必须晚于入住日期，未进行查询。');return msg('查询演示完成：只展示全程有房且无停售的房型。当前为固定样例，未查询真实数据库。');case'reprice':state.priceChanged=true;return msg('报价变化：11月11日由¥359变为¥379，新总价¥678。尚未创建订单，再次点击提交表示接受新报价（演示）。');case'create':if(state.hotel==='停业')return msg('酒店已停业，不能新订。');if(!val('contact')||!/^1[0-9]{10}$/.test(val('phone')))return msg('请检查联系人与11位联系电话。');if(+val('rooms')<1||+val('guests')<1||+val('guests')>2*+val('rooms'))return msg('房间数与人数非法，或超过房型容量。');state.booking='待确认';state.total=state.priceChanged?678:658;state.nights=2;state.version++;show('07');return msg('提交成功（演示）。订单待确认，库存逐夜预留一次。重复点击应使用同一请求键；本原型不实现服务器幂等持久化。');case'modifyFail':return msg('新日期无房，修改整体失败。原订单、原价格和原预留保持不变。');case'modify':if(state.booking!=='待确认')return msg('当前不是待确认，只允许按状态规则修改。');if(val('newOut')<=val('newIn'))return msg('新离店日期必须晚于入住日期。');state.nights=1;state.total=299;state.version++;return msg('修改演示成功：保留10日预留，释放11日，价格¥299，重置30分钟。此按钮仅演示图示的缩短日期场景。');case'cancel':if(!['待确认','已确认'].includes(state.booking))return msg('当前状态不可取消，不重复释放库存。');if(state.booking==='已确认'&&!confirm('真实系统须校验入住日当地18:00之前，是否演示符合截止条件？'))return;state.booking='已取消';state.version++;return msg('取消成功（演示），释放尚未消费的预留，不处理退款。');case'confirm':if(state.booking!=='待确认')return msg('当前状态不允许确认，请刷新。');state.booking='已确认';state.version++;return msg('已确认，不重复扣减库存。');case'reject':if(state.booking!=='待确认')return msg('当前状态不允许拒绝。');if(!val('rejectReason'))return msg('请填写拒绝原因。');state.booking='已拒绝';state.version++;return msg('拒绝成功，释放未消费预留并记录原因。');case'checkin':if(state.stay!=='已确认')return msg('重复入住被阻止，不重复变更状态或库存。');if(!confirm('现场已核验身份且今天符合计划入住日期？'))return;state.stay='已入住';return msg('现场样例订单 HB261110016 已入住。与顾客待确认样例是不同订单。');case'checkout':if(state.stay!=='已入住')return msg('只有已入住订单可正常退房。');state.stay='已退房';return msg('已退房，不恢复历史消费夜的库存，不能再次入住。');case'calendarSave':if(+val('supply')<2)return msg('保存失败：供给总量不能低于已有占用2间。');if(+val('supply')>10)return msg('保存失败：供给不能超过房型房间总数10间。');if(+val('nightPrice')<=0)return msg('价格必须大于0。');return msg('保存演示成功，记录价格/供给/停售变更；旧订单价格不变。');case'closeHotel':if(!val('closureReason'))return msg('请填写停业原因。');state.hotel='停业';return msg('酒店已停业，新订禁止。下一步逐单处理待确认和已确认订单；已入住保持状态。');case'openHotel':state.hotel='营业中';return msg('管理员手动恢复营业。');case'handleException':return msg('异常处置演示：选择一笔未入住订单，核对原因后取消并生成通知待办；已入住订单转人工协调。');case'approveHotel':return msg('酒店审核通过演示，记录审核人员与原因。');case'stats':return msg('统计口径：已确认、已入住、已退房共3单；2×3 + 1×1 + 1×2 = 9间夜。');case'logs':return msg('演示查询：依据登录身份过滤范围，日志只读且联系人脱敏。');case'refresh':return msg('已刷新演示状态；真实系统应重新读取当前版本。');case'lookup':return msg('查找到本酒店已确认样例订单 HB261110016。');case'createStaff':return msg('创建演示：工作人员唯一绑定酒店，禁止自行扩大权限。');case'disableStaff':return msg('停用账号演示：拒绝后续业务请求，保留原操作历史。');default:return msg('原型操作已触发。仅展示设计行为，未写入真实数据库。')}}
selector.onchange=()=>show(selector.value);document.querySelector('#close').onclick=()=>dialog.close();document.querySelector('#reset').onclick=()=>location.reload();show(current);</script></html>'''
    (SOURCE / '交互原型.html').write_text(document.replace('MANIFEST', data), encoding='utf-8')


if __name__ == '__main__':
    build_boards()
    exports()
