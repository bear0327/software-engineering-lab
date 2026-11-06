/* UI-only demonstrations of the explicit rules in report section 4.4.
 * The original prototype supplies pages, forms and ordinary actions.
 * Time is intentionally controllable; no real backend or database is involved.
 */
const baseAct = act;
const baseShow = show;
Object.assign(state, {
  now: Date.parse('2026-11-06T14:05:00+08:00'),
  expiresAt: Date.parse('2026-11-06T14:30:00+08:00'),
  releasedCount: 0,
  soldOut: false,
  hotelZone: 'Asia/Shanghai',
});

function inStatsRange(checkIn, start, end) {
  return start <= checkIn && checkIn <= end;
}

function expireBeforeWrite() {
  if (state.booking !== '待确认' || state.now < state.expiresAt) return false;
  state.booking = '已超时';
  state.version += 1;
  state.releasedCount += 1;
  msg('订单已到确认截止时刻，不能继续操作。已转为已超时，预留只释放一次；后台任务尚未执行也不影响截止判断。');
  return true;
}

show = function (key) {
  baseShow(key);
  const clock = new Intl.DateTimeFormat('zh-CN', {
    timeZone: state.hotelZone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(new Date(state.now));
  document.querySelector('#status').textContent += ` 演示时钟 ${clock}；${state.soldOut ? '指定日期停售' : '指定日期可售'}。`;
  if (key === '02') {
    const dateIn = canvas.querySelector('[data-name="checkIn"]');
    const dateOut = canvas.querySelector('[data-name="checkOut"]');
    const price = canvas.querySelector('[data-name="price"]');
    const updatePriceFilter = () => { price.disabled = !dateIn.value || !dateOut.value; };
    dateIn.addEventListener('input', updatePriceFilter);
    dateOut.addEventListener('input', updatePriceFilter);
    updatePriceFilter();
  }
};

act = function (action) {
  if (['confirm', 'reject', 'modify', 'modifyFail', 'cancel'].includes(action) && expireBeforeWrite()) return;
  if (action === 'expireDemo') {
    state.now = state.expiresAt;
    return msg('演示时钟已到确认截止。假定后台任务尚未处理，此时再次点击确认或修改，接口也会先转为已超时并拒绝操作。');
  }
  if (action === 'modifySoldOut') {
    if (expireBeforeWrite()) return;
    if (state.booking !== '待确认') return msg('只有待确认订单允许修改房间数量。');
    state.soldOut = true;
    return msg('修改被拒绝：拟将停售日期的占用从1间增加到2间，不符合“停售日期不能增加占用”的规则。原订单、原价格和库存保持不变；减少间数或缩短住宿仍可在其他条件满足时办理。');
  }
  if (action === 'modify') {
    if (state.hotel === '停业') return msg('酒店已停业，不能修改日期、房型或间数；可按规则取消订单。');
    if (state.soldOut && val('newOut') > '2026-11-12') {
      return msg('不能在停售日期新增占用。修改整体失败，原订单和库存保持不变。');
    }
  }
  if (action === 'create' && state.soldOut) return msg('所选日期已停售，不能新建预订。');
  if (action === 'search') {
    const start = val('checkIn'), end = val('checkOut');
    if (!start && !end) return msg('未指定住宿日期：仅浏览酒店和房型资料，不计算全程总价，不判断可订，价格范围筛选不可用。底图仍为固定设计样例。');
    if (!start || !end) return msg('请同时填写入住日期和离店日期。');
  }
  if (action === 'stats') {
    const start = val('statStart'), end = val('statEnd');
    if (!start || !end || end < start) return msg('请填写有效的统计日期区间。');
    const rows = [
      {date: '2026-11-01', roomNights: 6},
      {date: '2026-11-15', roomNights: 1},
      {date: '2026-11-30', roomNights: 2},
    ].filter(row => inStatsRange(row.date, start, end));
    const nights = rows.reduce((sum, row) => sum + row.roomNights, 0);
    return msg(`统计结果：${rows.length}单，${nights}间夜。按计划入住日纳入，开始日和结束日均包含；本例三笔订单分别在11月1日、15日和30日入住。`);
  }

  const oldVersion = state.version;
  if (action === 'calendarSave') {
    const supply = Number(val('supply')), price = Number(val('nightPrice'));
    if (supply >= 2 && supply <= 10 && price > 0) state.soldOut = val('sales') === '停售';
  }
  const result = baseAct(action);
  if (['create', 'modify'].includes(action) && state.version !== oldVersion && state.booking === '待确认') {
    state.expiresAt = state.now + 30 * 60 * 1000;
    if (action === 'create') state.releasedCount = 0;
    show(current);
  }
  return result;
};

show(current);
