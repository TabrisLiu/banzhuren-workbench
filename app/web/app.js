// 班主任小助手 · 前端逻辑（原生 JS，无构建依赖）
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let CFG = null, HOME = null, STUDENTS = [], CAL = null;
let clockOffset = 0;   // 服务器时间 - 本地时间 (ms)

function toast(msg, ms) {
  const t = $('#toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), ms || 2600);
}
async function api(url, opt) {
  const r = await fetch(url, opt);
  let j = {};
  try { j = await r.json(); } catch (e) { }
  if (!r.ok) throw new Error(j.error || j.detail || ('HTTP ' + r.status));
  return j;
}
function post(url, body) {
  return api(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
}
async function downloadPost(url, filename, body) { return _download(url, filename, { method: 'POST', headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined }); }
async function downloadGet(url, filename) { return _download(url, filename, { method: 'GET' }); }
async function _download(url, filename, opt) {
  try {
    const r = await fetch(url, opt);
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || '导出失败'); }
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = filename;
    a.click(); URL.revokeObjectURL(a.href);
    toast('已下载：' + filename);
  } catch (e) { toast('⚠ ' + e.message, 4000); }
}

/* ============ 实时时钟（启动联网校时，仅请求公开时间接口，不含本地数据） ============ */
async function syncTime() {
  try {
    const j = await api('/api/time');
    if (j.ok) {
      const net = new Date(j.now.replace(' ', 'T'));
      clockOffset = net - Date.now();
      $('#topDate').title = j.source === 'net' ? '时间已联网校准' : '网络不可用，使用本机时间';
    }
  } catch (e) { }
}
function tickClock() {
  const d = new Date(Date.now() + clockOffset);
  const p = n => String(n).padStart(2, '0');
  const clock = $('#topClock');
  if (clock) clock.textContent = p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  const ds = d.getFullYear() + '/' + (d.getMonth() + 1) + '/' + d.getDate() + ' 周' + '日一二三四五六'[d.getDay()];
  const td = $('#topDate');
  if (td && !td.dataset.set) td.textContent = ds;
}
setInterval(tickClock, 1000);
setInterval(syncTime, 30 * 60 * 1000);

/* ============ 初始化（服务未就绪时自动重试） ============ */
async function init() {
  let tries = 0;
  while (true) {
    try { CFG = await api('/api/config'); break; }
    catch (e) {
      tries++;
      const mask = $('#bootMask'), txt = $('#bootText');
      if (mask) {
        mask.style.display = 'flex';
        txt.textContent = '正在连接本地服务…（第 ' + tries + ' 次，服务启动中，请稍候）';
      }
      if (tries > 30) { if (txt) txt.textContent = '连接失败：请确认「启动工作台.bat」窗口已打开且未报错。'; return; }
      await new Promise(r => setTimeout(r, 2000));
    }
  }
  const mask = $('#bootMask'); if (mask) mask.style.display = 'none';
  fillTopbar();
  tickClock(); syncTime();
  if (!CFG.initialized) { startWizard(false); return; }
  refreshHome(); loadRoster();
  /* 支持 ?page=xxx 直达某页（也可用于收藏夹） */
  try {
    const p = new URLSearchParams(location.search).get('page');
    if (p && document.querySelector('.sidebar a[data-page="' + p + '"]')) openPage(p);
  } catch (e) { }
}
function fillTopbar() {
  const c = CFG.class || {};
  $('#clsLabel').textContent = (c.name || '未设置班级') + (c.major ? ' · ' + c.major : '');
  $('#topTeacher').textContent = c.head_teacher || '—';
}

/* ============ 页面切换 ============ */
$$('.sidebar a[data-page]').forEach(a => a.onclick = () => openPage(a.dataset.page));
function openPage(p) {
  $$('.page').forEach(s => s.classList.toggle('on', s.id === 'page-' + p));
  $$('.sidebar a').forEach(a => a.classList.toggle('on', a.dataset.page === p));
  if (p === 'home') refreshHome();
  if (p === 'roster') loadRoster();
  if (p === 'affairs') { loadLeaves(); loadNotices(); loadWarns(); loadAbsent(); }
  if (p === 'grades') { loadGradeList(); loadReport(); }
  if (p === 'intern') { loadInterns(); loadEmps(); }
  if (p === 'family') { loadParents(); loadFamily(); }
  if (p === 'mental') { loadTalks(); loadMentalWatch(); }
  if (p === 'culture') { loadRules(); loadActs(); loadQuants(); }
  if (p === 'stats') loadStats();
  if (p === 'personal') loadWorklog();
  if (p === 'dorm') loadDorm();
  if (p === 'awards') loadAwards();
  if (p === 'ext') loadExt();
  if (p === 'settings') { loadSettingsForm(); loadCalendar(); }
}
$$('.tabs').forEach(tb => tb.querySelectorAll('button[data-tab]').forEach(b => b.onclick = () => {
  tb.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
  const pane = tb.parentElement;
  pane.querySelectorAll(':scope > .tab-pane').forEach(p => p.classList.toggle('on', p.id === b.dataset.tab));
}));
function showTab(tabId) {
  $$('#page-affairs .tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === tabId));
  $$('#page-affairs .tab-pane').forEach(p => p.classList.toggle('on', p.id === tabId));
}

/* ============ 首页 ============ */
async function refreshHome() {
  try { HOME = await api('/api/home'); } catch (e) { toast(e.message); return; }
  const tc = HOME.todo_counts;
  const parts = [];
  if (tc.overdue) parts.push('<span class="item red">⚠ ' + tc.overdue + '项已逾期</span>');
  if (tc.today) parts.push('<span class="item">📅 ' + tc.today + '项今日到期</span>');
  if (HOME.attendance.leave.length) parts.push('<span class="item">' + HOME.attendance.leave.length + '人请假</span>');
  if (HOME.attendance.absent.length) parts.push('<span class="item red">' + HOME.attendance.absent.length + '人旷课</span>');
  if (!parts.length) parts.push('<span class="item">今日暂无到期事项 ✓</span>');
  $('#topSched').innerHTML = '<span class="lab">今日提醒</span>' + parts.join('');
  $('#homeDate').textContent = HOME.today + ' ' + HOME.weekday;
  try { const tc = $('#termChip'); tc.textContent = HOME.semester || ''; tc.style.display = HOME.semester ? '' : 'none'; } catch (e) { }
  const wk = $('#homeWeekTag');
  if (HOME.week_label) {
    wk.textContent = '📅 ' + HOME.week_label + (HOME.week_source === 'estimated' ? '（按开学日推算）' : '');
    wk.title = HOME.week_source === 'calendar' ? '来自已导入校历' : '可在「设置→校历」导入精确校历';
    wk.style.display = '';
  } else wk.style.display = 'none';
  /* 校历信息行：本周起止/备注 + 最近假期 */
  const calBox = $('#homeCal');
  if (HOME.calendar_loaded) {
    let parts = [];
    if (HOME.week_row) parts.push('<b>' + HOME.week_label + '</b>：' + esc(HOME.week_row.start) + ' ～ ' + esc(HOME.week_row.end) +
      (HOME.week_row.label ? '（' + esc(HOME.week_row.label) + '）' : ''));
    if (HOME.next_holiday) parts.push('🏕 下一假期：<b>' + esc(HOME.next_holiday.name || '假期') + '</b> ' + esc(HOME.next_holiday.start) + ' ～ ' + esc(HOME.next_holiday.end));
    if (parts.length) { calBox.innerHTML = parts.join('<br>'); calBox.style.display = ''; }
    else calBox.style.display = 'none';
  } else calBox.style.display = 'none';
  $('#homeWeek').textContent = HOME.week_label || '未设置';

  /* 日程信息流 */
  let sched = '';
  HOME.todos.filter(t => t.bucket === 'overdue' || t.bucket === 'today').forEach(t => {
    sched += '<div class="srow' + (t.bucket === 'today' ? ' cur' : '') + '"><span class="t">' +
      esc(t.bucket === 'overdue' ? '逾期' : (t.time || '今日')) + '</span><span class="x">' +
      esc(t.title) + ' <span class="cat">' + esc(t.category || '') + '</span></span>' +
      '<span class="pri ' + esc(t.priority || '中') + '">' + esc(t.priority || '中') + '</span></div>';
  });
  HOME.leaves_today.forEach(lv => {
    sched += '<div class="srow"><span class="t">请假</span><span class="x">' +
      esc(lv.student) + ' · ' + esc(lv.type) + ' ' + esc(lv.reason || '') + '</span></div>';
  });
  const tt = HOME.timetable[HOME.weekday] || {};
  Object.keys(tt).sort().forEach(p => {
    if (tt[p]) sched += '<div class="srow"><span class="t">' + esc(p) + '</span><span class="x">' + esc(tt[p]) + '</span></div>';
  });
  $('#homeSched').innerHTML = sched || '<div class="empty">今天没有日程与到期事项 — 对右侧 AI 助手说一句话即可创建</div>';

  /* 预警 */
  $('#homeWarns').innerHTML = HOME.warnings.length ? HOME.warnings.map(w =>
    '<div class="srow"><span class="t"><span class="dot ' + (w.level === '红' ? 'r' : 'y') + '"></span>' +
    esc(w.kind) + '</span><span class="x"><b>' + esc(w.student) + '</b> ' + esc(w.desc || '') + '</span>' +
    '<button class="btn sm" onclick="resolveWarn(\'' + w.uid + '\')">处理</button></div>').join('')
    : '<div class="empty">暂无未处理预警 ✓（成绩保存后学业预警自动生成）</div>';

  /* 本周课表 */
  const weeks = ['周一', '周二', '周三', '周四', '周五'];
  const pset = new Set();
  Object.values(HOME.timetable).forEach(d => Object.keys(d).forEach(p => d[p] && pset.add(p)));
  const periods = Array.from(pset).sort((a, b) => (a.includes('晚') ? 99 : parseInt(a)) - (b.includes('晚') ? 99 : parseInt(b)));
  if (!periods.length) periods.push('1-2节');
  let html = '<table class="t" style="text-align:center"><tr><th>节次</th>' +
    weeks.map(w => '<th' + (w === HOME.weekday ? ' style="background:#e8efff;color:#2b5fd9"' : '') + '>' + w + (w === HOME.weekday ? '(今)' : '') + '</th>').join('') + '</tr>';
  periods.forEach(p => {
    html += '<tr><td class="dl">' + p + '</td>' + weeks.map(w =>
      '<td' + (w === HOME.weekday && HOME.timetable[w][p] ? ' style="background:#f4f8ff;font-weight:600"' : '') + '>' +
      esc(HOME.timetable[w][p] || '—') + '</td>').join('') + '</tr>';
  });
  $('#homeTable').innerHTML = html + '</table>';

  /* 到校 */
  const a = HOME.attendance;
  if (!a.has_class) {
    $('#homeAtt').innerHTML = '<div class="empty">今日无课/周末 — 考勤按课表自动判断应到</div>';
  } else {
    $('#homeAtt').innerHTML = '<div class="kpis">' +
      '<div class="kpi acc"><b>' + a.expected + '</b><span>应到</span></div>' +
      '<div class="kpi green"><b>' + a.actual + '</b><span>实到</span></div>' +
      '<div class="kpi"><b>' + a.leave.length + '</b><span>请假</span></div>' +
      '<div class="kpi red"><b>' + a.absent.length + '</b><span>旷课</span></div></div>' +
      (a.leave.concat(a.absent, a.late).map(x =>
        '<div class="srow"><span class="t">' + (x.type || x.mark || '假') + '</span><span class="x"><b>' + esc(x.name) + '</b></span></div>').join('')
        || '<div class="empty">全员正常出勤 ✓</div>');
  }

  /* 待办 */
  const buckets = { overdue: '⛔ 已逾期', today: '📅 今日', todo: '📥 未完成', done: '✔ 已完成' };
  const grouped = {};
  HOME.todos.forEach(t => (grouped[t.bucket] = grouped[t.bucket] || []).push(t));
  let th = '<div class="row mb"><input id="newTodo" placeholder="＋ 快速添加待办（回车创建）" class="grow">' +
    '<input type="date" id="newTodoDue"><select id="newTodoPri"><option>高</option><option selected>中</option><option>低</option></select>' +
    '<button class="btn p" onclick="quickTodo()">添加</button></div>';
  // 全部为空时合并成一个空态，避免"已逾期/今日/未完成"三行"无"把看板撑得过高
  const hasOpen = !!(grouped.overdue || grouped.today || grouped.todo);
  if (!hasOpen) {
    th += '<div class="empty">暂无待办 ✓ 可在上方添加，或让 AI 助手帮你创建</div>';
  } else {
    Object.keys(buckets).forEach(b => {
      const items = grouped[b] || [];
      if (!items.length && b === 'done') return;
      th += '<h3 style="font-size:12.5px;margin:6px 0 2px;color:' + (b === 'overdue' ? '#c03030' : '#555') + '">' + buckets[b] + '（' + items.length + '）</h3>';
      th += items.map(t => '<div class="srow"><span class="x" style="' +
        (t.done ? 'color:#98a0af;text-decoration:line-through' : '') + '">' + esc(t.title) +
        (t.due ? ' <span class="dl">' + esc(t.due) + ' ' + esc(t.time || '') + '</span>' : '') +
        ' <span class="cat">' + esc(t.category || '班级管理') + '</span> <span class="pri ' + esc(t.priority) + '">' + esc(t.priority) + '</span></span>' +
        '<button class="btn sm" onclick="toggleTodo(\'' + t.uid + '\')">' + (t.done ? '↺' : '✓') + '</button>' +
        '<button class="btn sm" onclick="delTodo(\'' + t.uid + '\')">✕</button></div>').join('') ||
        '<div class="empty">无</div>';
    });
  }
  $('#homeTodos').innerHTML = th;
  $('#newTodo').addEventListener('keydown', e => { if (e.key === 'Enter') quickTodo(); });
}

/* ============ 待办 ============ */
async function quickTodo() {
  const t = $('#newTodo').value.trim(); if (!t) return;
  try {
    await post('/api/todos', { title: t, due: $('#newTodoDue').value, priority: $('#newTodoPri').value });
    $('#newTodo').value = ''; refreshHome(); toast('待办已创建 ✔');
  } catch (e) { toast(e.message); }
}
async function toggleTodo(uid) { try { await post('/api/todos/' + uid + '/toggle', {}); refreshHome(); } catch (e) { toast(e.message); } }
async function delTodo(uid) { try { await post('/api/todos/' + uid + '/delete', {}); refreshHome(); } catch (e) { toast(e.message); } }
function exportTodos() { downloadPost('/api/todos/export', '待办事项.xlsx'); }
function exportAttendance() { downloadPost('/api/attendance/export?date=' + (HOME ? HOME.today : ''), '考勤_' + (HOME ? HOME.today : '') + '.xlsx'); }

/* ============ 花名册 ============ */
let curTag = '';
async function loadRoster() {
  try {
    const j = await api('/api/students?q=' + encodeURIComponent($('#rosterQ')?.value || '') +
      (curTag ? '&tag=' + encodeURIComponent(curTag) : ''));
    STUDENTS = j.students;
    $('#rosterStats').textContent = '共 ' + j.stats.total + ' 人 · 在校 ' + j.stats.active +
      '（男' + j.stats.male + '/女' + j.stats.female + '）' +
      (j.stats.inactive.length ? ' · ' + j.stats.inactive.map(x => x.name + '(' + x.status + ')').join('、') : '');
    const tc = j.tag_counts || {};
    let chips = '<span class="dl">标签：</span><span class="tag ' + (curTag === '' ? 'b' : 'gr') + '" onclick="filterTag(\'\')">全部</span>';
    Object.keys(tc).forEach(k => { if (tc[k]) chips += '<span class="tag ' + (curTag === k ? 'b' : 'gr') + '" onclick="filterTag(\'' + k + '\')">' + k + ' ' + tc[k] + '</span>'; });
    $('#tagFilter').innerHTML = chips;
    let h = '<tr><th>学号</th><th>姓名</th><th>性别</th><th>宿舍</th><th>家长</th><th>电话</th><th>标签</th><th>状态</th></tr>';
    STUDENTS.forEach(s => {
      h += '<tr class="clickable' + (s.status !== '在校' ? ' hl-yel' : '') + '" onclick="openStudent(\'' + esc(s.student_id) + '\')">' +
        '<td>' + esc(s.student_id) + '</td><td><b>' + esc(s.name) + '</b></td><td>' + esc(s.gender || '') + '</td>' +
        '<td>' + esc(s.dorm || '') + '</td><td>' + esc(s.parent_name || '') + '</td><td>' + esc(s.parent_phone || '') + '</td>' +
        '<td>' + (s.tags || []).map(t => '<span class="tag b">' + esc(t) + '</span>').join('') + '</td>' +
        '<td>' + esc(s.status || '') + '</td></tr>';
    });
    $('#rosterTable').innerHTML = h + (STUDENTS.length ? '' : '<tr><td colspan="8" class="empty">暂无学生 — 点「＋新增」或「导入 Excel」</td></tr>');
  } catch (e) { toast(e.message); }
}
function filterTag(t) { curTag = t; loadRoster(); }
$('#rosterFile').addEventListener('change', async e => {
  const f = e.target.files[0]; if (!f) return;
  if (!/\.(xlsx|xlsm|xls)$/i.test(f.name)) { toast('请选择 .xls 或 .xlsx 格式的花名册文件（csv/wps 请先另存为 xlsx）', 6000); e.target.value = ''; return; }
  const fd = new FormData(); fd.append('file', f); fd.append('apply', '1');
  try {
    toast('解析中…', 1500);
    const r = await api('/api/roster/import', { method: 'POST', body: fd });
    if (r.meta && r.meta.error) {
      toast('⚠ 导入失败：' + r.meta.error + (r.meta.first_row && r.meta.first_row.length ? '（文件首行：' + r.meta.first_row.join(' | ') + '）' : ''), 10000);
    } else {
      const ap = r.applied || {};
      toast('导入完成：新增 ' + (ap.created || 0) + '、更新 ' + (ap.updated || 0) + '、解析 ' + r.count + ' 行 ✔', 6000);
      loadRoster(); refreshHome();
    }
  } catch (err) { toast('导入失败：' + err.message, 6000); }
  e.target.value = '';
});

/* 学生详情 */
async function openStudent(sid) {
  try {
    const s = await api('/api/students/' + encodeURIComponent(sid));
    $('#mTitle').textContent = s.name + ' · 一生一档';
    const tagNames = ['留守', '单亲', '学困', '退役士兵', '建档立卡', '心理关注', '班委', '竞赛', '全勤', '偏科', '临界'];
    const TAGKEY = { '留守': 'liushou', '单亲': 'danqin', '学困': 'xuekun', '退役士兵': 'tuishi', '建档立卡': 'jiandang', '心理关注': 'xinli', '班委': 'banwei', '竞赛': 'jingxuan', '全勤': 'qinjian', '偏科': 'pianke', '临界': 'linjie' };
    let h = '<div><h3 style="font-size:13px;margin-bottom:8px">基本信息 · 标签（点选切换）</h3><div class="row mb">' +
      tagNames.map(tn => '<span class="tag ' + ((s.tags || []).includes(TAGKEY[tn]) ? 'b' : 'gr') + '" onclick="toggleTag(\'' + esc(s.student_id) + '\',\'' + TAGKEY[tn] + '\')">' + tn + '</span>').join('') + '</div>';
    h += '<table class="t">';
    [['学号', s.student_id], ['性别', s.gender], ['出生日期', s.birth], ['生源', s.origin],
     ['专业', s.major], ['班级', s.class_name], ['宿舍', s.dorm], ['家长', (s.parent_name || '') + ' ' + (s.parent_phone || '')],
     ['住址', s.address], ['学籍状态', s.status], ['备注', s.remark]].forEach(([k, v]) => {
      h += '<tr><td class="dl" style="width:74px">' + k + '</td><td>' + esc(v || '—') + '</td></tr>';
    });
    h += '</table></div>';
    h += '<h3 style="font-size:13px;margin:14px 0 8px">成长时间线</h3>';
    h += '<div class="tl">' + ((s.timeline || []).map(e =>
      '<div class="ev"><span class="d">' + esc(e.ts || '') + '</span><span class="tag ' + (e.kind === '预警' ? 'r' : e.kind === '请假' ? 'y' : 'gr') + '">' + e.kind + '</span> ' + esc(e.text || '') + '</div>').join('') ||
      '<div class="empty">暂无记录（请假/预警/考勤联动后自动汇入）</div>') + '</div>';
    h += '<div class="row" style="margin-top:14px"><button class="btn p" onclick="openStudentEdit(\'' + esc(s.student_id) + '\')">✎ 编辑资料</button>' +
      '<button class="btn" onclick="downloadPost(\'/api/report/student/' + encodeURIComponent(s.student_id) + '\',\'成长档案_' + esc(s.name) + '.docx\')">📄 导出档案 Word</button>' +
      '<button class="btn danger" onclick="delStudent(\'' + esc(s.student_id) + '\')">删除（可撤销）</button></div>';
    $('#mBody').innerHTML = h;
    $('#stuModal').style.display = 'flex';
  } catch (e) { toast(e.message); }
}
async function toggleTag(sid, tag) {
  const cur = STUDENTS.find(s => s.student_id === sid);
  const on = !(cur && (cur.tags || []).includes(tag));
  try { await post('/api/students/' + encodeURIComponent(sid) + '/tags', { tag, on }); openStudent(sid); loadRoster(); }
  catch (e) { toast(e.message); }
}
async function delStudent(sid) {
  if (!confirm('确认删除 ' + sid + '？删除后「设置→撤销」可恢复。')) return;
  try { await post('/api/students/' + encodeURIComponent(sid) + '/delete', {}); closeModal('stuModal'); loadRoster(); refreshHome(); toast('已删除（可撤销）'); }
  catch (e) { toast(e.message); }
}
function closeModal(id) { $('#' + id).style.display = 'none'; }
$$('.modal-mask').forEach(m => m.addEventListener('click', e => { if (e.target === m) m.style.display = 'none'; }));

function openStudentEdit(sid) {
  const s = sid ? STUDENTS.find(x => x.student_id === sid) : null;
  $('#eTitle').textContent = s ? '编辑 · ' + s.name : '新增学生';
  $('#eOrigId').value = s ? s.student_id : '';
  $('#eId').value = s ? s.student_id : nextStudentId();
  $('#eName').value = s ? s.name : ''; $('#eGender').value = s ? (s.gender || '男') : '男';
  $('#eBirth').value = s ? (s.birth || '') : ''; $('#eOrigin').value = s ? (s.origin || '') : '';
  $('#eMajor').value = s ? (s.major || '') : (CFG.class.major || ''); $('#eDorm').value = s ? (s.dorm || '') : '';
  $('#eParent').value = s ? (s.parent_name || '') : ''; $('#ePhone').value = s ? (s.parent_phone || '') : '';
  $('#ePRel').value = s ? (s.parent_relation || '') : '';
  $('#eParent2').value = s ? (s.parent_name2 || '') : ''; $('#ePRel2').value = s ? (s.parent_relation2 || '') : ''; $('#ePhone2').value = s ? (s.parent_phone2 || '') : '';
  $('#eStatus').value = s ? (s.status || '在校') : '在校'; $('#eAddr').value = s ? (s.address || '') : '';
  closeModal('stuModal'); $('#editModal').style.display = 'flex';
}
function nextStudentId() {
  const ids = STUDENTS.map(s => s.student_id).filter(x => /^\d+$/.test(x)).map(Number);
  if (!ids.length) return '';
  return String(Math.max(...ids) + 1);
}
async function saveStudent() {
  const body = {
    student_id: $('#eId').value.trim(), name: $('#eName').value.trim(), gender: $('#eGender').value,
    birth: $('#eBirth').value.trim(), origin: $('#eOrigin').value.trim(), major: $('#eMajor').value.trim(),
    class_name: CFG.class.name, dorm: $('#eDorm').value.trim(), parent_name: $('#eParent').value.trim(),
    parent_relation: $('#ePRel').value.trim(), parent_phone: $('#ePhone').value.trim(),
    parent_name2: $('#eParent2').value.trim(), parent_relation2: $('#ePRel2').value.trim(), parent_phone2: $('#ePhone2').value.trim(),
    address: $('#eAddr').value.trim(), status: $('#eStatus').value,
  };
  if (!body.student_id || !body.name) { toast('学号与姓名必填'); return; }
  try {
    await post('/api/students', body);
    closeModal('editModal'); loadRoster(); refreshHome();
    if (typeof loadParents === 'function' && $('#page-family').classList.contains('on')) loadParents();
    toast('已保存 ✔');
  } catch (e) { toast(e.message); }
}

/* ============ 日常事务：请假 / 缺勤 / 通知 / 预警 ============ */
async function addLeave() {
  try {
    await post('/api/leaves', {
      student: $('#lvStu').value.trim(), type: $('#lvType').value, start_date: $('#lvDate').value,
      days: parseInt($('#lvDays').value || '1'), reason: $('#lvReason').value.trim(), attachment: $('#lvAtt').checked
    });
    toast('已登记请假 ✔ 考勤自动联动'); loadLeaves(); refreshHome();
  } catch (e) { toast(e.message); }
}
async function loadLeaves() {
  try {
    const j = await api('/api/leaves');
    $('#leaveTable').innerHTML = '<tr><th>学生</th><th>类型</th><th>起止</th><th>事由</th><th>附件</th><th>状态</th></tr>' +
      j.leaves.map(l => '<tr><td>' + esc(l.student) + '</td><td>' + esc(l.type) + '</td><td>' + esc(l.start_date) + ' ~ ' + esc(l.end_date || '') +
        '</td><td>' + esc(l.reason || '') + '</td><td>' + (l.attachment ? '📷' : '—') + '</td><td><span class="tag g">' + esc(l.status) + '</span></td></tr>').join('') ||
      '<tr><td colspan="6" class="empty">暂无请假记录</td></tr>';
  } catch (e) { }
}
/* 缺勤 */
async function markAbsent() {
  if (!$('#abStu').value.trim()) { toast('学生姓名必填'); return; }
  try {
    await post('/api/attendance/mark', { date: $('#abDate').value, student: $('#abStu').value.trim(),
      mark: $('#abMark').value, reason: $('#abReason').value.trim() });
    toast('已登记 ' + $('#abMark').value + ' ✔'); loadAbsent(); refreshHome();
  } catch (e) { toast(e.message); }
}
async function loadAbsent() {
  try {
    const d = $('#abDate').value;
    const a = await api('/api/attendance' + (d ? '?date=' + d : ''));
    $('#absentToday').innerHTML = a.has_class
      ? '<div class="kpis"><div class="kpi acc"><b>' + a.expected + '</b><span>应到</span></div>' +
        '<div class="kpi green"><b>' + a.actual + '</b><span>实到</span></div>' +
        '<div class="kpi"><b>' + a.leave.length + '</b><span>请假</span></div>' +
        '<div class="kpi red"><b>' + a.absent.length + '</b><span>旷课</span></div></div>' +
        (a.leave.concat(a.absent, a.late).map(x => '<div class="srow"><span class="t">' +
          (x.type || x.mark || '假') + '</span><span class="x"><b>' + esc(x.name) + '</b> ' + esc(x.reason || '') + '</span></div>').join('')
          || '<div class="empty">该日无缺勤记录</div>')
      : '<div class="empty">' + a.date + ' 无课/周末</div>';
  } catch (e) { }
}
/* 通知 */
async function loadNotices() {
  try {
    const j = await api('/api/home');
    const ns = j.notices || [];
    $('#noticeList').innerHTML = ns.length ? ns.map(n =>
      '<div class="card" style="margin-bottom:9px"><div class="row"><b>' + esc(n.title) + '</b> <span class="tag ' +
      (n.status === '已发布' ? 'g' : 'gr') + '">' + esc(n.status) + '</span><span class="dl">' + esc(n.audience) +
      (n.status === '已发布' ? ' · 已读 ' + (n.read_count || 0) + '/' + n.total : '') + '</span>' +
      '<span class="grow-sp"></span>' +
      '<button class="btn sm" onclick="copyNotice(\'' + n.uid + '\')">📋复制</button>' +
      (n.status !== '已发布' ? '<button class="btn sm p" onclick="sendNotice(\'' + n.uid + '\')">标记已发到群</button>' +
        '<button class="btn sm" onclick="readOne(\'' + n.uid + '\',' + (n.read_count || 0) + ')">记1人已读</button>' : '') +
      '</div><div class="dl" style="white-space:pre-wrap;margin-top:6px">' + esc(n.content || '') + '</div></div>').join('')
      : '<div class="empty">暂无通知 — 可对 AI 说「帮我写一份国庆放假安全通知」生成草稿</div>';
    window._NOTICES = ns;
  } catch (e) { }
}
async function saveNotice() {
  if (!$('#ntTitle').value.trim()) { toast('标题必填'); return; }
  await post('/api/notices', { title: $('#ntTitle').value.trim(), content: $('#ntBody').value, audience: $('#ntAudience').value });
  toast('草稿已保存 ✔'); loadNotices();
}
function copyNotice(uid) {
  const n = (window._NOTICES || []).find(x => x.uid === uid); if (!n) return;
  navigator.clipboard.writeText(n.content || '').then(() => toast('已复制，去粘贴到微信群 ✔'));
}
async function sendNotice(uid) { await post('/api/notices/' + uid + '/send', {}); toast('已标记发布'); loadNotices(); }
async function readOne(uid, cur) { await post('/api/notices/' + uid + '/read', { read_count: cur }); loadNotices(); }
/* 预警 */
async function addWarning() {
  if (!$('#wStu').value.trim()) { toast('学生姓名必填'); return; }
  await post('/api/warnings', { student: $('#wStu').value.trim(), kind: $('#wKind').value, level: $('#wLevel').value, desc: $('#wDesc').value.trim() });
  toast('预警已登记 ✔'); loadWarns(); refreshHome();
}
async function loadWarns() {
  try {
    const j = await api('/api/home');
    $('#warnList').innerHTML = j.warnings.length ? j.warnings.map(w =>
      '<div class="srow"><span class="t"><span class="dot ' + (w.level === '红' ? 'r' : 'y') + '"></span>' + esc(w.kind) + '</span>' +
      '<span class="x"><b>' + esc(w.student) + '</b> ' + esc(w.desc || '') + ' <span class="dl">' + esc(w.created_at) + '</span></span>' +
      '<button class="btn sm" onclick="resolveWarn(\'' + w.uid + '\')">处理</button></div>').join('')
      : '<div class="empty">暂无未处理预警</div>';
  } catch (e) { }
}
async function resolveWarn(uid) { await post('/api/warnings/' + uid + '/resolve', {}); toast('已标记处理'); refreshHome(); loadWarns(); }

/* ============ 课表（弹层） ============ */
function openTimetableModal() { $('#ttModal').style.display = 'flex'; loadTimetable(); }
async function loadTimetable() {
  try {
    const j = await api('/api/timetable');
    $('#ttList').innerHTML = '<tr><th>星期</th><th>节次</th><th>课程</th><th>教师</th><th>教室</th><th>周次区间</th><th></th></tr>' +
      j.entries.map(e => '<tr><td>' + esc(e.weekday) + '</td><td>' + esc(e.period) + '</td><td>' + esc(e.course) +
        '</td><td>' + esc(e.teacher || '') + '</td><td>' + esc(e.room || '') + '</td><td class="dl">' +
        (e.odd === 'odd' ? '单周 ' : e.odd === 'even' ? '双周 ' : '') + esc(e.weeks || '') + '</td>' +
        '<td><button class="btn sm" onclick="delTimetable(\'' + e.uid + '\')">✕</button></td></tr>').join('') ||
      '<tr><td colspan="7" class="empty">暂无课表 — 逐格添加、粘贴文本或导入全学期 Excel</td></tr>';
    window._TT = j.entries;
  } catch (e) { }
}
async function addTimetable() {
  const c = $('#ttCourse').value.trim(); if (!c) { toast('请填写课程名'); return; }
  const entries = (window._TT || []).filter(e => !(e.weekday === $('#ttWeek').value && e.period === $('#ttPeriod').value));
  entries.push({ weekday: $('#ttWeek').value, period: $('#ttPeriod').value, course: c });
  await post('/api/timetable', { entries });
  toast('已添加 ✔'); $('#ttCourse').value = ''; loadTimetable(); refreshHome();
}
async function delTimetable(uid) {
  const entries = (window._TT || []).filter(e => e.uid !== uid);
  await post('/api/timetable', { entries }); loadTimetable(); refreshHome();
}
$('#ttFile') && $('#ttFile').addEventListener('change', async e => {
  const f = e.target.files[0]; if (!f) return;
  const text = await f.text();
  const entries = [];
  text.split(/\r?\n/).forEach(line => {
    const p = line.split(/[,，\t]/);
    if (p.length >= 3) entries.push({ weekday: p[0].trim(), period: p[1].trim(), course: p[2].trim() });
  });
  if (!entries.length) { toast('未解析到有效行（每行需 周X,节次,课程）', 4000); e.target.value = ''; return; }
  await post('/api/timetable', { entries });
  toast('已导入 ' + entries.length + ' 节课 ✔'); loadTimetable(); refreshHome(); e.target.value = '';
});

/* ============ 学业与成绩 ============ */
let REP = null;
async function saveGrades() {
  const exam = $('#grExam').value.trim(), subject = $('#grSubject').value.trim();
  if (!exam || !subject) { toast('考试名称与科目必填'); return; }
  const items = [];
  $('#grScores').value.split(/\r?\n/).forEach(line => {
    const m = line.trim().match(/^(.+?)[,，\s]+(\d+(?:\.\d+)?)$/);
    if (m) items.push({ key: m[1].trim(), score: m[2] });
  });
  if (!items.length) { toast('未解析到成绩行（每行：学号或姓名 分数）', 4000); return; }
  const byName = {}, byId = {};
  STUDENTS.forEach(s => { byName[s.name] = s; byId[s.student_id] = s; });
  const rows = [], unknown = [];
  items.forEach(it => {
    const s = byId[it.key] || byName[it.key];
    if (s) rows.push({ student_id: s.student_id, name: s.name, score: it.score });
    else unknown.push(it.key);
  });
  if (unknown.length) { toast('以下学生不在花名册：' + unknown.join('、'), 5000); return; }
  try {
    const r = await post('/api/grades', { exam, subject, date: $('#grDate').value,
      full: parseFloat($('#grFull').value || 100), items: rows });
    let msg = '已保存 ✔（' + rows.length + ' 人）';
    if (r.warnings_raised && r.warnings_raised.length) msg += ' 触发学业预警：' + r.warnings_raised.join('；');
    $('#grSaveResult').textContent = msg;
    toast(msg, 6000);
    $('#grScores').value = '';
    loadGradeList(); loadReport(true); refreshHome();
  } catch (e) { toast(e.message); }
}
async function loadGradeList() {
  try {
    const j = await api('/api/grades');
    $('#gradeList').innerHTML = '<table class="t"><tr><th>日期</th><th>考试</th><th>科目</th><th>满分</th><th>人数</th><th>分数范围</th><th></th></tr>' +
      j.sheets.map(g => {
        const vals = g.items.map(x => x.score);
        return '<tr><td>' + esc(g.date) + '</td><td>' + esc(g.exam) + '</td><td>' + esc(g.subject) + '</td><td>' + (g.full || 100) + '</td><td>' +
          g.items.length + '</td><td>' + (vals.length ? Math.min(...vals) + ' ~ ' + Math.max(...vals) : '—') + '</td>' +
          '<td><button class="btn sm" onclick="delGrade(\'' + g.uid + '\')">删除</button></td></tr>';
      }).join('') || '<tr><td colspan="7" class="empty">暂无成绩 — 先到「成绩录入」保存一次</td></tr></table>';
  } catch (e) { }
}
async function delGrade(uid) { await post('/api/grades/' + uid + '/delete', {}); loadGradeList(); loadReport(true); refreshHome(); }

function showGrTab(tabId) {
  $$('#page-grades .tabs button').forEach(b => { if (b.dataset.tab === tabId) b.click(); });
}
async function loadReport() {
  try {
    const cur = $('#anaExam').value;
    const j = await api('/api/grades/report' + (cur ? '?exam=' + encodeURIComponent(cur) : ''));
    $('#anaExam').innerHTML = (j.exams || []).map(e =>
      '<option' + (e.exam === j.exam ? ' selected' : '') + '>' + esc(e.exam) + '</option>').join('') ||
      '<option value="">暂无考试</option>';
    REP = j.report;
    renderAna();
  } catch (e) { toast(e.message); }
}
function _bars(subjects) {
  if (!subjects.length) return '';
  const n = subjects.length;
  const W = Math.max(640, 90 + n * 86), H = 250, top = 30, plotH = 160;
  const maxV = Math.max.apply(null, subjects.map(s => s.avg)) * 1.12 || 1;
  let grid = '', bars = '';
  for (let i = 0; i <= 4; i++) {
    const y = top + plotH - i * plotH / 4, v = (maxV * i / 4).toFixed(0);
    grid += '<line x1="50" y1="' + y + '" x2="' + (W - 30) + '" y2="' + y + '" stroke="#eef1f6"/>' +
      '<text x="42" y="' + (y + 4) + '" text-anchor="end" font-size="10.5" fill="#9aa3b2">' + v + '</text>';
  }
  subjects.forEach((s, i) => {
    const slot = (W - 90) / n, bw = Math.min(46, slot * 0.55);
    const x = 60 + i * slot + (slot - bw) / 2;
    const h = Math.max(2, plotH * s.avg / maxV);
    bars += '<rect x="' + x + '" y="' + (top + plotH - h) + '" width="' + bw + '" height="' + h + '" rx="3" fill="#6c93e8"/>' +
      '<text x="' + (x + bw / 2) + '" y="' + (top + plotH - h - 5) + '" text-anchor="middle" font-size="11.5" font-weight="600" fill="#2b3a55">' + s.avg + '</text>' +
      '<text x="' + (x + bw / 2) + '" y="' + (top + plotH + 18) + '" text-anchor="middle" font-size="12" fill="#667">' + esc(s.subject) + '</text>';
  });
  return '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;max-width:' + W + 'px">' + grid + bars + '</svg>';
}
function _lineChart(trend) {
  if (!trend.length) return '';
  const W = Math.max(560, 120 + trend.length * 110), H = 240, top = 26, plotH = 160;
  const maxV = Math.max.apply(null, trend.map(t => t.avg_ratio).concat([100]));
  const pts = trend.map((t, i) => ({ x: 70 + (W - 140) * (trend.length === 1 ? 0.5 : i / (trend.length - 1)),
    y: top + plotH - plotH * t.avg_ratio / maxV, t: t }));
  let grid = '';
  for (let i = 0; i <= 4; i++) {
    const y = top + plotH - i * plotH / 4;
    grid += '<line x1="50" y1="' + y + '" x2="' + (W - 30) + '" y2="' + y + '" stroke="#eef1f6"/>' +
      '<text x="42" y="' + (y + 4) + '" text-anchor="end" font-size="10.5" fill="#9aa3b2">' + (maxV * i / 4).toFixed(0) + '%</text>';
  }
  return '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;max-width:' + W + 'px">' + grid +
    '<polyline points="' + pts.map(p => p.x + ',' + p.y).join(' ') + '" fill="none" stroke="#6c93e8" stroke-width="2.5"/>' +
    pts.map(p => '<circle cx="' + p.x + '" cy="' + p.y + '" r="4" fill="#2b5fd9"/>' +
      '<text x="' + p.x + '" y="' + (p.y - 9) + '" text-anchor="middle" font-size="11.5" font-weight="600" fill="#2b3a55">' + p.t.avg_ratio + '%</text>' +
      '<text x="' + p.x + '" y="' + (top + plotH + 18) + '" text-anchor="middle" font-size="11" fill="#667">' + esc(p.t.exam) + '</text>' +
      '<text x="' + p.x + '" y="' + (top + plotH + 32) + '" text-anchor="middle" font-size="10" fill="#9aa3b2">' + esc(p.t.date) + '</text>').join('') +
    '</svg>';
}
function _tiers(t) {
  const colors = { 'A(≥90%)': '#3ba15c', 'B(80-90)': '#6c93e8', 'C(70-80)': '#8fb0f0', 'D(60-70)': '#e0a13b', 'E(<60)': '#c03050' };
  const tot = Object.values(t).reduce((a, b) => a + b, 0) || 1;
  let acc = 0;
  const stops = Object.keys(t).map(k => {
    const a = (acc / tot) * 360; acc += t[k];
    return colors[k] + ' ' + a.toFixed(1) + 'deg ' + ((acc / tot) * 360).toFixed(1) + 'deg';
  }).join(',');
  let h = '<div class="row" style="gap:16px;align-items:center">';
  h += '<div class="pie" style="width:96px;height:96px;background:conic-gradient(' + stops + ')"></div><div>';
  Object.keys(t).forEach(k => h += '<span class="leg" style="justify-content:flex-start;margin:2px 0"><i style="background:' + colors[k] + '"></i>' + k + ' · ' + t[k] + ' 人</span><br>');
  return h + '</div></div>';
}
function renderAna() {
  const empty = '<div class="empty">暂无成绩数据 — 点「＋ 录入新考试」录入各科成绩</div>';
  ['anaOv', 'anaDetail', 'anaSubj', 'anaRank', 'anaMove', 'anaTrend'].forEach(id => {
    document.getElementById(id).innerHTML = '';
  });
  if (!REP) { $('#anaOv').innerHTML = empty; $('#anaMeta').textContent = '选择一场考试查看完整分析'; return; }
  const k = REP.kpi;
  $('#anaMeta').textContent = REP.exam + ' · ' + REP.date + ' · ' + k.subjects + ' 个科目';
  /* 综合概览 */
  let h = '<div class="kpis" style="grid-template-columns:repeat(4,1fr)">' +
    '<div class="kpi acc"><b>' + k.count + '</b><span>参考人数</span><small>学科 ' + k.subjects + ' 门</small></div>' +
    '<div class="kpi"><b>' + k.avg_total + '</b><span>班级平均总分</span><small>满分 ' + k.full_total + '</small></div>' +
    '<div class="kpi"><b>' + k.max_total + ' / ' + k.min_total + '</b><span>最高 / 最低</span><small>极差 ' + k.range + '</small></div>' +
    '<div class="kpi green"><b>' + k.tier_good + '</b><span>优良（A+B）人数</span><small>平均得分率 ' + k.avg_ratio + '%</small></div></div>';
  h += '<h3 style="font-size:13.5px;margin:12px 0 4px">📊 各学科平均分对比</h3>' + _bars(REP.subjects);
  h += '<div class="hrow2" style="margin-top:12px"><div class="card" style="margin:0"><h3>💡 关注学科（平均分最低）</h3>' +
    (REP.focus.map(f => '<div class="srow"><span class="x"><b>' + esc(f.subject) + '</b> · 平均 ' + f.avg + ' / ' + f.full +
      ' · 及格率 ' + f.pass_rate + '%</span>' + (f.failed_n ? '<span class="tag r">不及格 ' + f.failed_n + ' 人</span>' : '<span class="tag g">全及格</span>') + '</div>').join('') || '<div class="empty">无</div>') +
    '</div><div class="card" style="margin:0"><h3>⭐ 总分前列</h3>' +
    REP.top.slice(0, 8).map(d => '<div class="srow"><span class="rank-num' + (d.rank <= 3 ? ' g' + d.rank : '') + '">' + d.rank + '</span>' +
      '<span class="x"><b>' + esc(d.name) + '</b> · ' + d.total + ' 分 · 得分率 ' + d.ratio + '%</span></div>').join('') +
    '</div></div>';
  h += '<h3 style="font-size:13.5px;margin:14px 0 4px">🎯 总分得分率分布</h3>' + _tiers(k.tiers);
  if (REP.failed_students.length) {
    h += '<h3 style="font-size:13.5px;margin:14px 0 4px;color:#c03030">不及格明细（' + REP.failed_students.length + ' 人次）</h3>' +
      '<div class="row">' + REP.failed_students.map(f => '<span class="tag y">' + esc(f.name) + ' · ' + esc(f.subject) + ' ' + f.score + '</span>').join('') + '</div>';
  }
  document.getElementById('anaOv').innerHTML = h;
  /* 成绩明细 */
  const subs = REP.subjects.map(s => s.subject);
  const fullOf = {};
  REP.subjects.forEach(s => fullOf[s.subject] = s.full);
  h = '<div style="overflow-x:auto"><table class="t"><tr><th>名次</th><th>姓名</th>' +
    subs.map(s => '<th>' + esc(s) + '</th>').join('') + '<th>总分</th><th>得分率</th></tr>' +
    REP.detail.map(d => {
      let cells = subs.map(s => {
        const v = d.scores[s];
        if (v == null) return '<td class="dl">缺考</td>';
        if (v < 0.6 * (fullOf[s] || 100)) return '<td style="color:#c03030;font-weight:600">' + v + '</td>';
        return '<td>' + v + '</td>';
      }).join('');
      return '<tr><td>' + d.rank + '</td><td><b>' + esc(d.name) + '</b></td>' + cells +
        '<td><b>' + d.total + '</b></td><td>' + d.ratio + '%</td></tr>';
    }).join('') + '</table></div>';
  document.getElementById('anaDetail').innerHTML = h;
  /* 学科分析 */
  h = '<table class="t"><tr><th>科目</th><th>满分</th><th>平均</th><th>最高</th><th>最低</th><th>及格率</th><th>优秀率</th><th>不及格名单</th></tr>' +
    REP.subjects.map(s => '<tr><td><b>' + esc(s.subject) + '</b></td><td>' + s.full + '</td><td>' + s.avg + '</td><td>' + s.max + '</td><td>' + s.min + '</td>' +
      '<td>' + s.pass_rate + '%</td><td>' + s.excellent + '%</td>' +
      '<td class="dl">' + (s.failed.map(f => esc(f.name) + '(' + f.score + ')').join('、') || '—') + '</td></tr>').join('') + '</table>';
  document.getElementById('anaSubj').innerHTML = h;
  /* 排名分析 */
  h = '<div style="max-height:420px;overflow-y:auto"><table class="t"><tr><th>名次</th><th>学号</th><th>姓名</th><th>总分</th><th>得分率</th></tr>' +
    REP.ranking.map(d => '<tr' + (d.rank <= 3 ? ' class="hl-yel"' : '') + '><td><span class="rank-num' + (d.rank <= 3 ? ' g' + d.rank : '') + '">' + d.rank + '</span></td>' +
      '<td class="dl">' + esc(d.student_id) + '</td><td><b>' + esc(d.name) + '</b></td><td>' + d.total + '</td><td>' + d.ratio + '%</td></tr>').join('') + '</table></div>';
  document.getElementById('anaRank').innerHTML = h;
  /* 进退步 */
  if (REP.prev_exam) {
    h = '<div class="hint mb">与上次考试「' + esc(REP.prev_exam) + '」总分对比</div><div class="grid2"><div>' +
      '<h3 style="font-size:13.5px;margin-bottom:6px;color:#2e8b57">▲ 进步榜</h3>' +
      (REP.up.map(u => '<div class="srow"><span class="x"><b>' + esc(u.name) + '</b> ' + u.prev + ' → ' + u.curr + ' 分</span><span class="delta-up">+' + u.delta + '</span></div>').join('') || '<div class="empty">无</div>') +
      '</div><div><h3 style="font-size:13.5px;margin-bottom:6px;color:#c03030">▼ 退步榜</h3>' +
      (REP.down.map(u => '<div class="srow"><span class="x"><b>' + esc(u.name) + '</b> ' + u.prev + ' → ' + u.curr + ' 分</span><span class="delta-down">' + u.delta + '</span></div>').join('') || '<div class="empty">无</div>') +
      '</div></div>';
  } else h = '<div class="empty">至少录入两场考试（同一批学生）后可对比进退步</div>';
  document.getElementById('anaMove').innerHTML = h;
  /* 历次趋势 */
  h = '<div class="hint mb">各场考试班级平均得分率走势</div>' + _lineChart(REP.trend) +
    (REP.trend.length > 1 ? '' : '<div class="empty" style="margin-top:6px">再录入一场考试即可形成趋势线</div>');
  document.getElementById('anaTrend').innerHTML = h;
}
$$('.subtabs button').forEach(b => b.onclick = () => {
  $$('.subtabs button').forEach(x => x.classList.toggle('on', x === b));
  ['ov', 'detail', 'subj', 'rank', 'move', 'trend'].forEach(k => {
    const id = 'ana' + k[0].toUpperCase() + k.slice(1);
    const el = document.getElementById(id);
    if (el) el.style.display = (k === b.dataset.ana) ? '' : 'none';
  });
});
function exportReport() {
  if (!REP) { toast('请先录入成绩'); return; }
  downloadPost('/api/grades/report/export', '学业分析_' + REP.exam + '.docx', { exam: REP.exam });
}

/* ============ 实习与就业 ============ */
async function addIntern() {
  if (!$('#itStu').value.trim() || !$('#itCompany').value.trim()) { toast('学生与单位必填'); return; }
  await post('/api/ledger/internships', {
    student: $('#itStu').value.trim(), company: $('#itCompany').value.trim(), post: $('#itPost').value.trim(),
    mentor: $('#itMentor').value.trim(), phone: $('#itPhone').value.trim(),
    start: $('#itStart').value, end: $('#itEnd').value, status: '进行中' });
  toast('实习已登记 ✔'); loadInterns();
}
async function loadInterns() {
  try {
    const j = await api('/api/ledger/internships');
    $('#internTable').innerHTML = '<tr><th>学生</th><th>单位</th><th>岗位</th><th>企业导师</th><th>起止</th><th>状态</th><th></th></tr>' +
      j.items.map(x => '<tr><td>' + esc(x.student) + '</td><td>' + esc(x.company) + '</td><td>' + esc(x.post || '') + '</td>' +
        '<td>' + esc(x.mentor || '') + ' ' + esc(x.phone || '') + '</td><td>' + esc(x.start || '') + ' ~ ' + esc(x.end || '') + '</td>' +
        '<td>' + esc(x.status || '') + '</td><td><button class="btn sm" onclick="delLedger(\'internships\',\'' + x.uid + '\',loadInterns)">✕</button></td></tr>').join('') ||
      '<tr><td colspan="7" class="empty">暂无实习记录</td></tr>';
  } catch (e) { }
}
async function addEmp() {
  if (!$('#emStu').value.trim()) { toast('学生姓名必填'); return; }
  await post('/api/ledger/internships', {
    student: $('#emStu').value.trim(), type: '就业意向', direction: $('#emDir').value,
    city: $('#emCity').value.trim(), note: $('#emNote').value.trim(), status: '意向' });
  toast('就业意向已登记 ✔'); loadEmps();
}
async function loadEmps() {
  try {
    const j = await api('/api/ledger/internships');
    const emps = j.items.filter(x => x.type === '就业意向');
    $('#empTable').innerHTML = '<tr><th>学生</th><th>方向</th><th>意向城市</th><th>备注</th><th></th></tr>' +
      emps.map(x => '<tr><td>' + esc(x.student) + '</td><td>' + esc(x.direction || '') + '</td><td>' + esc(x.city || '') + '</td>' +
        '<td>' + esc(x.note || '') + '</td><td><button class="btn sm" onclick="delLedger(\'internships\',\'' + x.uid + '\',loadEmps)">✕</button></td></tr>').join('') ||
      '<tr><td colspan="5" class="empty">暂无就业意向记录</td></tr>';
  } catch (e) { }
}
async function delLedger(name, uid, reload) {
  await post('/api/ledger/' + name + '/' + uid + '/delete', {}); reload();
}

/* ============ 家校沟通：家长名单 ============ */
let PARENTS = [], parentMissingOnly = false;
function toggleMissing() {
  parentMissingOnly = !parentMissingOnly;
  $('#btnMissing').classList.toggle('p', parentMissingOnly);
  loadParents();
}
async function loadParents() {
  try {
    const q = $('#parentQ') ? $('#parentQ').value.trim() : '';
    const j = await api('/api/parents?q=' + encodeURIComponent(q) + (parentMissingOnly ? '&only_missing=1' : ''));
    PARENTS = j.parents || [];
    const st = j.stats || {};
    $('#parentStats').innerHTML = '共 ' + (st.total || 0) + ' 人 · 已填 ' + (st.filled || 0) +
      (st.missing ? ' · <b style="color:var(--red)">缺失 ' + st.missing + '</b>' : '');
    let h = '<tr><th>学号</th><th>学生</th><th>家长姓名</th><th>关系</th><th>联系电话</th><th>最近沟通</th><th></th></tr>';
    PARENTS.forEach(p => {
      const p1 = [esc(p.parent_name || ''), esc(p.parent_relation || '')].filter(Boolean).join(' · ');
      const p2 = esc(p.parent_name2 || '');
      const tel = (v) => v ? '<a class="tel" href="tel:' + esc(v) + '" title="点击拨号">' + esc(v) + '</a>' : '<span class="dl">—</span>';
      h += '<tr' + (p.status !== '在校' ? ' class="hl-yel"' : '') + '>' +
        '<td>' + esc(p.student_id) + '</td>' +
        '<td><b>' + esc(p.name) + '</b>' + (p.dorm ? ' <span class="dl">' + esc(p.dorm) + '</span>' : '') + '</td>' +
        '<td>' + (p1 || '<span class="dl">—</span>') + (p2 ? '<div class="dl" style="font-size:11.5px">' + p2 + '</div>' : '') + '</td>' +
        '<td>' + esc(p.parent_relation || '') + '</td>' +
        '<td>' + tel(p.parent_phone) + (p.parent_phone2 ? '<div style="font-size:11.5px">' + tel(p.parent_phone2) + '</div>' : '') + '</td>' +
        '<td>' + (p.last_contact ? esc(p.last_contact) + ' <span class="dl">×' + (p.contact_count || 0) + '</span>' : '<span class="dl">未联系</span>') + '</td>' +
        '<td style="white-space:nowrap"><button class="btn sm" onclick="openStudentEdit(\'' + esc(p.student_id) + '\')">编辑</button> ' +
        (p.parent_phone ? '<button class="btn sm" onclick="copyPhone(\'' + esc(p.parent_phone) + '\')">复制</button>' : '') + '</td></tr>';
    });
    $('#parentTable').innerHTML = h + (PARENTS.length ? '' : '<tr><td colspan="7" class="empty">' +
      (parentMissingOnly ? '没有缺失家长联系方式的学生 ✔' : '暂无学生 — 请先到「花名册」导入学生') + '</td></tr>');
  } catch (e) { toast(e.message); }
}
function copyPhone(v) {
  navigator.clipboard.writeText(v).then(() => toast('已复制：' + v)).catch(() => toast('复制失败，请手动选择'));
}
$('#parentFile').addEventListener('change', async e => {
  const f = e.target.files[0]; if (!f) return;
  if (!/\.(xlsx|xlsm|xls)$/i.test(f.name)) {
    toast('请选择 .xls 或 .xlsx 格式的家长名单（csv/wps 请先另存为 xlsx）', 6000); e.target.value = ''; return;
  }
  const fd = new FormData(); fd.append('file', f); fd.append('apply', '1');
  try {
    toast('解析中…', 1500);
    const r = await api('/api/parents/import', { method: 'POST', body: fd });
    if (r.meta && r.meta.error) {
      toast('⚠ 导入失败：' + r.meta.error, 10000);
    } else {
      const ap = r.applied || {};
      let msg = '导入完成：更新 ' + (ap.updated || 0) + ' 人、解析 ' + r.count + ' 行';
      if (ap.unchanged) msg += '、无变化 ' + ap.unchanged;
      if (ap.unmatched_count) {
        const names = (ap.unmatched || []).slice(0, 3).map(u => u.name || u.student_id || '空行').join('、');
        msg += '、未匹配 ' + ap.unmatched_count + ' 行（' + names + (ap.unmatched_count > 3 ? ' 等' : '') + '）';
      }
      toast(msg, 9000);
      loadParents(); loadRoster();
    }
  } catch (err) { toast('导入失败：' + err.message, 6000); }
  e.target.value = '';
});

/* ============ 家校沟通：台账 ============ */
async function addFamily() {
  if (!$('#fcStu').value.trim() || !$('#fcContent').value.trim()) { toast('学生与内容必填'); return; }
  await post('/api/ledger/family', {
    date: $('#fcDate').value, student: $('#fcStu').value.trim(), way: $('#fcWay').value,
    content: $('#fcContent').value.trim(), followup: $('#fcFollow').value.trim(), status: '已沟通' });
  toast('已记录 ✔'); loadFamily();
}
async function loadFamily() {
  try {
    const j = await api('/api/ledger/family');
    $('#familyTable').innerHTML = '<tr><th>日期</th><th>学生</th><th>方式</th><th>内容</th><th>后续跟进</th><th></th></tr>' +
      j.items.map(x => '<tr><td>' + esc(x.date || '') + '</td><td>' + esc(x.student) + '</td><td>' + esc(x.way || '') + '</td>' +
        '<td>' + esc(x.content || '') + '</td><td>' + esc(x.followup || '') + '</td>' +
        '<td><button class="btn sm" onclick="delLedger(\'family\',\'' + x.uid + '\',loadFamily)">✕</button></td></tr>').join('') ||
      '<tr><td colspan="6" class="empty">暂无沟通记录</td></tr>';
  } catch (e) { }
}

/* ============ 思政与心理 ============ */
async function addTalk() {
  if (!$('#tkStu').value.trim()) { toast('学生姓名必填'); return; }
  await post('/api/ledger/talks', {
    date: $('#tkDate').value, student: $('#tkStu').value.trim(), topic: $('#tkTopic').value.trim(),
    state: $('#tkState').value.trim(), action: $('#tkAction').value.trim() });
  toast('谈心记录已保存 ✔'); loadTalks();
}
async function loadTalks() {
  try {
    const j = await api('/api/ledger/talks');
    $('#talkTable').innerHTML = '<tr><th>日期</th><th>学生</th><th>主题</th><th>当时状态</th><th>教育措施</th><th></th></tr>' +
      j.items.map(x => '<tr><td>' + esc(x.date || '') + '</td><td>' + esc(x.student) + '</td><td>' + esc(x.topic || '') + '</td>' +
        '<td>' + esc(x.state || '') + '</td><td>' + esc(x.action || '') + '</td>' +
        '<td><button class="btn sm" onclick="delLedger(\'talks\',\'' + x.uid + '\',loadTalks)">✕</button></td></tr>').join('') ||
      '<tr><td colspan="6" class="empty">暂无谈心记录</td></tr>';
  } catch (e) { }
}
async function loadMentalWatch() {
  try {
    const [w, s] = await Promise.all([api('/api/home'), api('/api/students')]);
    const psychWarns = w.warnings.filter(x => x.kind === '心理');
    const tagStu = s.students.filter(x => (x.tags || []).includes('xinli'));
    let h = '';
    psychWarns.forEach(x => h += '<div class="srow"><span class="t"><span class="dot ' + (x.level === '红' ? 'r' : 'y') + '"></span>预警</span>' +
      '<span class="x"><b>' + esc(x.student) + '</b> ' + esc(x.desc || '') + '</span>' +
      '<button class="btn sm" onclick="resolveWarn(\'' + x.uid + '\')">处理</button></div>');
    tagStu.forEach(x => h += '<div class="srow"><span class="t">标签</span><span class="x"><b>' + esc(x.name) + '</b> 心理关注 · ' + esc(x.dorm || '') + '</span></div>');
    $('#mentalWatch').innerHTML = h || '<div class="empty">暂无心理关注对象（预警登记选「心理」或给学生打「心理关注」标签）</div>';
  } catch (e) { }
}

/* ============ 班级文化 ============ */
async function loadRules() {
  try { const j = await api('/api/culture'); $('#cuRules').value = j.rules || ''; } catch (e) { }
}
async function saveRules() { await post('/api/culture', { rules: $('#cuRules').value }); toast('班规已保存 ✔'); }
async function addActivity() {
  if (!$('#acTitle').value.trim()) { toast('活动名称必填'); return; }
  await post('/api/ledger/activities', { date: $('#acDate').value, title: $('#acTitle').value.trim(), desc: $('#acDesc').value.trim() });
  toast('活动已记录 ✔'); loadActs();
}
async function loadActs() {
  try {
    const j = await api('/api/ledger/activities');
    $('#actTable').innerHTML = '<tr><th>日期</th><th>活动</th><th>内容/总结</th><th></th></tr>' +
      j.items.map(x => '<tr><td>' + esc(x.date || '') + '</td><td>' + esc(x.title || '') + '</td><td>' + esc(x.desc || '') + '</td>' +
        '<td><button class="btn sm" onclick="delLedger(\'activities\',\'' + x.uid + '\',loadActs)">✕</button></td></tr>').join('') ||
      '<tr><td colspan="4" class="empty">暂无活动记录</td></tr>';
  } catch (e) { }
}
async function addQuant() {
  if (!$('#qtWeek').value.trim()) { toast('周次必填'); return; }
  const h = parseFloat($('#qtHyg').value || 0), d = parseFloat($('#qtDisc').value || 0), s = parseFloat($('#qtStudy').value || 0);
  await post('/api/ledger/quant', { week: $('#qtWeek').value.trim(), hygiene: h, discipline: d, study: s,
    total: Math.round((h + d + s) * 10) / 10, note: $('#qtNote').value.trim() });
  toast('量化已登记 ✔'); loadQuants();
}
async function loadQuants() {
  try {
    const j = await api('/api/ledger/quant');
    $('#quantTable').innerHTML = '<tr><th>周次</th><th>卫生</th><th>纪律</th><th>学习</th><th>总分</th><th>备注</th><th></th></tr>' +
      j.items.map(x => '<tr><td>' + esc(x.week || '') + '</td><td>' + x.hygiene + '</td><td>' + x.discipline + '</td><td>' + x.study + '</td>' +
        '<td><b>' + x.total + '</b></td><td>' + esc(x.note || '') + '</td>' +
        '<td><button class="btn sm" onclick="delLedger(\'quant\',\'' + x.uid + '\',loadQuants)">✕</button></td></tr>').join('') ||
      '<tr><td colspan="7" class="empty">暂无量化记录</td></tr>';
  } catch (e) { }
}

/* ============ 数据统计 ============ */
async function loadStats() {
  try {
    const s = await api('/api/stats');
    let h = '<div class="kpis">' +
      '<div class="kpi acc"><b>' + s.total + '</b><span>在册人数</span></div>' +
      '<div class="kpi"><b>' + s.male + ' : ' + s.female + '</b><span>男女比例</span></div>' +
      '<div class="kpi green"><b>' + s.active + '</b><span>在校</span></div>' +
      '<div class="kpi red"><b>' + s.warnings_total + '</b><span>未处理预警</span></div></div>';
    h += '<div class="grid2"><div>';
    h += '<h3 style="font-size:13px;margin:8px 0 6px">生源地分布</h3><table class="t">';
    s.origin.forEach(([k, v]) => h += '<tr><td>' + esc(k) + '</td><td>' + v + ' 人</td></tr>');
    h += '</table>';
    h += '<h3 style="font-size:13px;margin:12px 0 6px">标签分布</h3><div class="row">' +
      (s.tag_counts.map(([k, v]) => '<span class="tag b">' + k + ' ' + v + '</span>').join('') || '<span class="dl">暂无标签</span>') + '</div>';
    h += '</div><div>';
    h += '<h3 style="font-size:13px;margin:8px 0 6px">近 30 天考勤（有课 ' + s.attend_days + ' 天）</h3><table class="t">' +
      '<tr><td>请假人次</td><td>' + s.leave_cnt + '</td></tr><tr><td>旷课人次</td><td>' + s.absent_cnt + '</td></tr></table>';
    h += '<h3 style="font-size:13px;margin:12px 0 6px">预警分布</h3><div class="row">' +
      (Object.keys(s.warnings_by_kind).map(k => '<span class="tag y">' + k + ' ' + s.warnings_by_kind[k] + '</span>').join('') || '<span class="dl">无</span>') + '</div>';
    if (s.inactive.length) h += '<h3 style="font-size:13px;margin:12px 0 6px">非在校</h3><div class="row">' +
      s.inactive.map(x => '<span class="tag gr">' + esc(x.name) + '(' + esc(x.status) + ')</span>').join('') + '</div>';
    h += '</div></div>';
    $('#statsBody').innerHTML = h;
  } catch (e) { toast(e.message); }
}

/* ============ 个人工作 ============ */
async function loadWorklog() {
  try {
    if (!$('#wlDate').value) $('#wlDate').value = _dstr(new Date());
    const j = await api('/api/worklog?date=' + $('#wlDate').value);
    if (j.current) {
      $('#wlDone').value = j.current.done || ''; $('#wlProblem').value = j.current.problem || ''; $('#wlPlan').value = j.current.plan || '';
    } else { $('#wlDone').value = ''; $('#wlProblem').value = ''; $('#wlPlan').value = ''; }
    $('#wlRecent').innerHTML = '<table class="t"><tr><th>日期</th><th>今日完成</th><th>问题</th><th>明日计划</th></tr>' +
      j.recent.map(w => '<tr><td>' + esc(w.date) + '</td><td>' + esc((w.done || '').slice(0, 40)) + '</td><td>' + esc((w.problem || '').slice(0, 24)) + '</td><td>' + esc((w.plan || '').slice(0, 24)) + '</td></tr>').join('') ||
      '<tr><td colspan="4" class="empty">暂无日志</td></tr></table>';
  } catch (e) { }
}
async function saveWorklog() {
  await post('/api/worklog', { date: $('#wlDate').value, done: $('#wlDone').value, problem: $('#wlProblem').value, plan: $('#wlPlan').value });
  $('#wlSaved').textContent = '已保存 ' + new Date().toLocaleTimeString('zh-CN');
  loadWorklog(); toast('日志已保存 ✔');
}
$('#wlDate') && $('#wlDate').addEventListener('change', loadWorklog);

/* ============ 设置 ============ */
function loadSettingsForm() {
  const c = CFG.class, s = CFG.semester, a = CFG.ai, g = CFG.settings || {};
  $('#stClassName').value = c.name || ''; $('#stMajor').value = c.major || '';
  $('#stGrade').value = c.grade || ''; $('#stTeacher').value = c.head_teacher || ''; $('#stPhone').value = c.phone || '';
  $('#stSemName').value = s.name || ''; $('#stSemStart').value = s.start_date || ''; $('#stSemWeeks').value = s.total_weeks || 20;
  const prov = a.provider === 'custom' ? 'custom' : 'deepseek';
  document.querySelector('input[name="aiProv"][value="' + prov + '"]').checked = true;
  $('#stBaseUrl').value = a.base_url || ''; $('#stModel').value = a.model || '';
  aiProvToggle();
  $('#stKey').placeholder = a.has_key ? '已设置（' + esc(a.api_key) + '），留空则不修改' : '粘贴 API Key';
  $('#stWarnFail').value = g.warn_fail_courses || 2; $('#stWarnDrop').value = g.warn_score_drop || 10;
  $('#stLeaveNotice').checked = !!g.leave_notify_parent;
  try { $('#stDataDir').value = CFG.storage && CFG.storage.data_dir ? CFG.storage.data_dir : '(程序文件夹)'; } catch (e) { }
  loadSemList();
}
async function saveSettings() {
  CFG = await post('/api/config', {
    class: { name: $('#stClassName').value.trim(), major: $('#stMajor').value.trim(), grade: $('#stGrade').value.trim(), head_teacher: $('#stTeacher').value.trim(), phone: $('#stPhone').value.trim() },
    semester: { name: $('#stSemName').value.trim(), start_date: $('#stSemStart').value, total_weeks: $('#stSemWeeks').value }
  });
  fillTopbar(); toast('班级设置已保存 ✔');
}
async function saveAiSettings() {
  const prov = document.querySelector('input[name="aiProv"]:checked').value;
  const ai = { provider: prov, api_key: $('#stKey').value.trim() };
  if (prov === 'custom') { ai.base_url = $('#stBaseUrl').value.trim(); ai.model = $('#stModel').value.trim(); }
  const body = {
    ai: ai,
    settings: { warn_fail_courses: $('#stWarnFail').value, warn_score_drop: $('#stWarnDrop').value, leave_notify_parent: $('#stLeaveNotice').checked }
  };
  CFG = await post('/api/config', body);
  $('#stKey').value = '';
  loadSettingsForm(); toast('AI 设置已保存 ✔（仅存本机）'); refreshHome();
}
async function undoLast() { try { const r = await post('/api/undo', {}); toast(r.msg + ' ✔'); refreshHome(); loadRoster(); } catch (e) { toast(e.message); } }
async function loadOps() {
  try {
    const j = await api('/api/ops');
    $('#opsList').innerHTML = '<table class="t"><tr><th>时间</th><th>文件</th><th>动作</th><th>来源</th><th>对象</th></tr>' +
      (j.ops.map(o => '<tr><td class="dl">' + esc(o.ts) + '</td><td>' + esc(o.file) + '</td><td>' + esc(o.action) +
        '</td><td>' + esc(o.source) + '</td><td class="dl">' + esc(o.uid) + '</td></tr>').join('') ||
        '<tr><td colspan="5" class="empty">暂无操作</td></tr>') + '</table>';
  } catch (e) { }
}
async function loadBackups() {
  try {
    const j = await api('/api/backup/list');
    $('#backupList').innerHTML = (j.backups.map(b =>
      '<div class="srow"><span class="t">' + esc(b.date) + '</span><span class="x">' + b.count + ' 份快照 · ' + b.files.slice(0, 4).map(esc).join('，') + '…</span></div>').join('') ||
      '<div class="empty">暂无备份（首次写入后生成）</div>');
  } catch (e) { }
}
/* 数据包导入导出 + 迁移 */
$('#backupFile') && $('#backupFile').addEventListener('change', async e => {
  const f = e.target.files[0]; if (!f) return;
  if (!confirm('导入将覆盖当前全部班级数据（导入前自动快照），确定继续？')) { e.target.value = ''; return; }
  const fd = new FormData(); fd.append('file', f);
  try {
    toast('导入中…', 2000);
    const r = await api('/api/backup/import', { method: 'POST', body: fd });
    toast(r.msg + ' ✔', 5000);
    CFG = await api('/api/config');
    fillTopbar(); refreshHome(); loadRoster(); loadSettingsForm();
  } catch (err) { toast('导入失败：' + err.message, 5000); }
  e.target.value = '';
});
async function moveStorage() {
  const p = $('#stMoveDir').value.trim();
  if (!p) { toast('请填写新位置路径'); return; }
  if (!confirm('确认把数据迁移到：\n' + p + '\n\n迁移后建议重启服务。')) return;
  try {
    const r = await post('/api/storage/move', { path: p });
    toast(r.msg, 6000);
    CFG = await api('/api/config');
    loadSettingsForm();
  } catch (e) { toast(e.message, 5000); }
}

/* ============ 新学期 / 学期档案 ============ */
async function loadSemList() {
  try {
    const j = await api('/api/semesters');
    const row = $('#semListRow'); if (!row) return;
    let h = '';
    (j.list || []).forEach(x => {
      h += '<span class="tag ' + (x.name === j.active ? 'b' : 'gr') + '" style="cursor:default" title="开学 ' + esc(x.start || '未设置') + '">' +
        esc(x.name) + (x.name === j.active ? ' · 当前' : '') + '</span>';
    });
    row.innerHTML = h || '<span class="hint">尚无学期档案</span>';
  } catch (e) { }
}
async function startNewSemester() {
  const name = $('#nsName').value.trim();
  if (!name) { toast('学期名称必填'); return; }
  if (!confirm('开始新学期「' + name + '」？\n切换后旧学期数据仍保留，建议接着：①设置→校历 点选上课日 ②导入本学期课表。')) return;
  try {
    const r = await post('/api/semester/new', { name, start: $('#nsStart').value, weeks_n: $('#nsWeeks').value });
    toast(r.msg, 6000);
    CFG = await api('/api/config');
    fillTopbar(); refreshHome(); loadSemList(); loadSettingsForm();
  } catch (e) { toast(e.message); }
}

/* ============ 校历：点选上课日 ============ */
/* CAL_TARGET：当前日历渲染目标。null=设置页 #calMini；向导内指向 #wzCalMini */
let CAL_DAYS = new Set();
let CAL_TARGET = null;
let WZ_CAL_DIRTY = false;   // 向导内是否点选过（用于向导完成时决定是否保存校历）
function _calEl() { return CAL_TARGET || document.getElementById('calMini'); }
function _calInWz() { const el = _calEl(); return !!el && el.id === 'wzCalMini'; }
async function loadCalendar() {
  try {
    const j = await api('/api/calendar');
    CAL_DAYS = new Set(j.calendar.class_days || []);
    renderCalMini();
  } catch (e) { }
}
function _dstr(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
function renderCalMini(el) {
  const target = el || _calEl(); if (!target) return;
  const cfgS = (CFG.semester || {});
  let start = cfgS.start_date, weeksN = cfgS.total_weeks || 20;
  // 向导内：跟随面板上「开学日期/总周数」的实时输入重算范围
  if (target.id === 'wzCalMini') {
    const s = document.getElementById('wSemStart'), w = document.getElementById('wSemWeeks');
    if (s && s.value) start = s.value;
    if (w && w.value) weeksN = parseInt(w.value) || 20;
  }
  if (!start) { const t = new Date(); start = t.getFullYear() + '-09-01'; }
  const sd = new Date(start);
  const from = new Date(sd.getFullYear(), sd.getMonth(), 1);
  const to = new Date(sd.getTime()); to.setDate(to.getDate() + weeksN * 7); to.setMonth(to.getMonth() + 1, 0);
  let h = '';
  const months = [];
  let m = new Date(from.getFullYear(), from.getMonth(), 1);
  while (m <= to && months.length < 10) { months.push(new Date(m)); m.setMonth(m.getMonth() + 1); }
  months.forEach((mo, mi) => {
    h += '<div class="cm-m"><div class="cm-head" style="grid-column:1/-1">' + mo.getFullYear() + ' 年 ' + (mo.getMonth() + 1) + ' 月</div>';
    h += ['一', '二', '三', '四', '五', '六', '日'].map(w => '<div class="cm-h">周' + w + '</div>').join('');
    const first = new Date(mo.getFullYear(), mo.getMonth(), 1);
    const lead = (first.getDay() + 6) % 7;
    for (let i = 0; i < lead; i++) h += '<div class="cm-d blank"></div>';
    const days = new Date(mo.getFullYear(), mo.getMonth() + 1, 0).getDate();
    for (let d = 1; d <= days; d++) {
      const ds = mo.getFullYear() + '-' + String(mo.getMonth() + 1).padStart(2, '0') + '-' + String(d).padStart(2, '0');
      h += '<div class="cm-d' + (CAL_DAYS.has(ds) ? ' on' : '') + '" onclick="calToggle(\'' + ds + '\',event)">' + d + '</div>';
    }
    h += '</div>';
  });
  target.innerHTML = h;
  calState();
}
function calToggle(ds, ev) {
  if (ev && ev.shiftKey) { // 整周快速选：以该日所在周为一周批量切换
    calWholeWeek(ds); return;
  }
  if (CAL_DAYS.has(ds)) CAL_DAYS.delete(ds); else CAL_DAYS.add(ds);
  if (_calInWz()) WZ_CAL_DIRTY = true;
  renderCalMini();
}
function calWholeWeek(ds) {
  const d0 = new Date(ds + 'T00:00:00');
  const mon = new Date(d0.getTime() - ((d0.getDay() + 6) % 7) * 864e5);
  const on = !CAL_DAYS.has(_dstr(mon));
  for (let i = 0; i < 7; i++) {
    const dd = new Date(mon.getTime() + i * 864e5);
    const key = _dstr(dd);
    if (on) CAL_DAYS.add(key); else CAL_DAYS.delete(key);
  }
  if (_calInWz()) WZ_CAL_DIRTY = true;
  renderCalMini();
}
function calQuickWhole() { toast('在日历上直接点某天；按住 Shift 点一天可整周批量选择', 5000); }
function calClear() {
  if (!confirm('清空当前校历？')) return;
  CAL_DAYS = new Set();
  if (_calInWz()) WZ_CAL_DIRTY = true;
  renderCalMini();
}
function calState() {
  const inWz = _calInWz();
  const tag = $(inWz ? '#wzCalState' : '#calState'), cnt = $(inWz ? '#wzCalCount' : '#calCount');
  const n = CAL_DAYS.size;
  if (tag) { tag.textContent = n ? '已设置 · ' + n + ' 个上课日' : '未设置'; tag.className = 'tag ' + (n ? 'g' : 'gr'); tag.style.marginLeft = 'auto'; }
  if (cnt) {
    const weeks = n ? Math.ceil(n / 5) : 0;
    cnt.textContent = n ? '约 ' + weeks + ' 个教学周' : '';
  }
}
async function saveCalendarDays() {
  await post('/api/calendar', { mode: 'days', class_days: Array.from(CAL_DAYS).sort() });
  toast('校历已保存 ✔ 首页将显示第几周', 5000);
  refreshHome();
}

/* ============ AI 对话 ============ */
function chatBubble(cls, html) {
  const d = document.createElement('div'); d.className = cls; d.innerHTML = html;
  $('#chatBody').appendChild(d); $('#chatBody').scrollTop = $('#chatBody').scrollHeight;
  return d;
}
function ensureChatGreet() {
  if ($('#chatBody').dataset.greet) return;
  $('#chatBody').dataset.greet = 1;
  chatBubble('msg a', '我是本机 AI 助手。直接说事即可：\n· "张子豪今天感冒发烧，请假一天"\n· "新建待办：周五下午3点找刘思远谈心"\n· "帮我写一份国庆放假安全通知"\n· "全班现在多少人？"\n写入前都会让你确认，全部变更可撤销。');
}
async function sendChat(text) {
  text = (text || '').trim(); if (!text) return;
  if (!(CFG.ai && CFG.ai.has_key)) { toast('请先在 ⚙ 设置中填入 DeepSeek API Key', 4000); return; }
  chatBubble('msg u', esc(text));
  const wait = chatBubble('msg a', '<span class="dl">思考中…</span>');
  $('#chatInput').value = '';
  let r;
  try { r = await post('/api/ai/chat', { text }); }
  catch (e) { wait.className = 'msg err'; wait.textContent = e.message; return; }
  wait.remove();
  if (r.reply) chatBubble('msg a', esc(r.reply));
  if (r.questions && r.questions.length)
    chatBubble('msg a', '<b>请核对：</b>\n' + r.questions.map(q => '· ' + esc(q)).join('\n'));
  if (r.actions && r.actions.length) showActionCard(r.actions);
}
function showActionCard(actions) {
  const card = document.createElement('div'); card.className = 'op-card';
  card.innerHTML = '<h5>即将写入本地数据库 · 请确认</h5><pre>' +
    esc(JSON.stringify(actions, null, 1)) + '</pre>' +
    '<div class="op-btns"><button class="btn sm p">✔ 确认写入</button><button class="btn sm">取消</button></div>';
  $('#chatBody').appendChild(card);
  const btns = card.querySelectorAll('.op-btns .btn');
  btns[0].onclick = async () => {
    btns[0].disabled = btns[1].disabled = true; btns[0].textContent = '写入中…';
    try {
      const r = await post('/api/ai/confirm', { actions });
      card.querySelector('pre').remove(); card.querySelector('.op-btns').remove();
      (r.results || []).forEach(x => {
        const div = document.createElement('div');
        div.className = 'result-line ' + (x.ok ? 'ok' : 'bad');
        div.textContent = (x.ok ? '✔ ' : '✗ ') + x.msg;
        card.appendChild(div);
      });
      chatBubble('msg a', '已落库 ✔ 首页、考勤、档案已联动更新（<a style="color:var(--blue);cursor:pointer" onclick="openPage(\'home\')">查看首页</a>）');
      refreshHome();
    } catch (e) { btns[0].disabled = btns[1].disabled = false; btns[0].textContent = '重试'; toast(e.message); }
  };
  btns[1].onclick = () => { card.querySelector('.op-btns').innerHTML = '<span class="dl">已取消，未写入</span>'; };
  $('#chatBody').scrollTop = $('#chatBody').scrollHeight;
}
$('#chatSend').onclick = () => sendChat($('#chatInput').value);
$('#chatInput').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat($('#chatInput').value); }
});
function wireChips(containerId, inputEl) {
  const box = document.getElementById(containerId);
  if (!box) return;
  box.addEventListener('click', e => {
    const c = e.target.closest('.chip'); if (!c) return;
    inputEl.value = c.dataset.fill || c.textContent.replace(/^[＋]/, '');
    inputEl.focus();
  });
}
wireChips('chatChips', $('#chatInput'));
async function clearChat() {
  if (!confirm('确定清除全部对话记录？此操作不影响已写入的数据。')) return;
  try { await post('/api/ai/history/clear', {}); } catch (e) { }
  $('#chatBody').innerHTML = ''; $('#chatBody').dataset.greet = ''; ensureChatGreet();
  toast('对话已清除');
}
async function loadHistory() {
  try {
    const j = await api('/api/ai/history');
    if (j.messages && j.messages.length) {
      j.messages.forEach(m => chatBubble(m.role === 'user' ? 'msg u' : 'msg a', esc(m.content)));
      $('#chatBody').dataset.greet = 1;
    }
  } catch (e) { }
}
/* 对话栏：宽屏折叠 / 窄屏抽屉 */
function isNarrow() { return window.matchMedia('(max-width:1180px)').matches; }
$('#chatToggle').onclick = () => {
  if (isNarrow()) document.body.classList.toggle('chat-open');
  else document.body.classList.toggle('chat-closed');
};

/* 侧栏抽屉（窄屏） */
function isMobileNav() { return window.matchMedia('(max-width:960px)').matches; }
$('#navToggle').onclick = () => document.body.classList.toggle('nav-open');
$('#scrim').onclick = () => document.body.classList.remove('nav-open', 'chat-open');
$$('.sidebar a[data-page]').forEach(a => a.addEventListener('click', () => {
  if (isMobileNav()) document.body.classList.remove('nav-open');
}));
window.addEventListener('resize', () => {
  if (!isNarrow()) document.body.classList.remove('chat-open');
  if (!isMobileNav()) document.body.classList.remove('nav-open');
});

/* ============ 首用向导 ============ */
const WZ_LAST = 4;
let wzStep = 1;
function startWizard(restart) {
  wzStep = 1; WZ_CAL_DIRTY = false; renderWizard();
  $('#wizard').style.display = 'flex';
  $('#wzSkip').style.display = restart || CFG.initialized ? 'none' : '';
}
function renderWizard() {
  $$('.wz-dot').forEach((d, i) => d.classList.toggle('on', i === wzStep - 1));
  $$('.wz-pane').forEach((p, i) => p.classList.toggle('on', i === wzStep - 1));
  $('#wzBack').style.visibility = wzStep > 1 ? 'visible' : 'hidden';
  $('#wzNext').textContent = wzStep < WZ_LAST ? '下一步' : (CFG.initialized ? '保存' : '完成设置');
  if (wzStep === 2) wzRenderCal();   // 学期与校历页：进入即渲染可点选日历
}
/* 向导内的校历：切到该页时加载一次已有设置，并渲染进 wzCalMini */
let WZ_CAL_LOADED = false;
async function wzRenderCal() {
  CAL_TARGET = document.getElementById('wzCalMini');
  if (!WZ_CAL_LOADED) {
    try {
      const j = await api('/api/calendar');
      CAL_DAYS = new Set(j.calendar.class_days || []);
      WZ_CAL_LOADED = true;
    } catch (e) { }
  }
  renderCalMini(CAL_TARGET);
}
function wzSemChanged() { if (wzStep === 2) renderCalMini(document.getElementById('wzCalMini')); }
$('#wzBack').onclick = () => { if (wzStep > 1) { wzStep--; renderWizard(); } };
$('#wzSkip').onclick = () => finishWizard(true);
$('#wzNext').onclick = async () => {
  if (wzStep === 1) {
    if (!$('#wClassName').value.trim() || !$('#wMajor').value.trim()) { toast('班级名称与专业必填'); return; }
    wzStep = 2; renderWizard(); return;
  }
  if (wzStep < WZ_LAST) { wzStep++; renderWizard(); return; }
  await finishWizard(false);
};
function wAiProvToggle() {
  const prov = document.querySelector('input[name="wAiProv"]:checked');
  const box = document.getElementById('wAiCustomBox');
  if (prov && box) box.style.display = prov.value === 'custom' ? '' : 'none';
}
async function finishWizard(skip) {
  const body = { wizard_done: true };
  if (!skip) {
    body.class = { name: $('#wClassName').value.trim(), major: $('#wMajor').value.trim(), grade: $('#wGrade').value.trim(), head_teacher: $('#wTeacher').value.trim(), phone: $('#wPhone').value.trim(), size_expect: parseInt($('#wSize').value || '40') };
    body.semester = { name: $('#wSemName').value.trim(), start_date: $('#wSemStart').value, total_weeks: $('#wSemWeeks').value };
    const prov = document.querySelector('input[name="wAiProv"]:checked').value;
    body.ai = { provider: prov, api_key: $('#wKey').value.trim() };
    if (prov === 'custom') { body.ai.base_url = $('#wBaseUrl').value.trim(); body.ai.model = $('#wModel').value.trim(); }
    const dd = $('#wDataDir').value.trim();
    if (dd) body.storage = { data_dir: dd };
  }
  try {
    CFG = await post('/api/config', body);
    // 向导内点选过上课日 → 一并保存校历
    if (!skip && WZ_CAL_DIRTY) {
      try { await post('/api/calendar', { mode: 'days', class_days: Array.from(CAL_DAYS).sort() }); } catch (e) { }
    }
    $('#wizard').style.display = 'none';
    CAL_TARGET = null; WZ_CAL_DIRTY = false; WZ_CAL_LOADED = false;
    fillTopbar(); refreshHome(); loadRoster();
    if (!skip) toast('设置完成 ✔ 现在可以导入花名册或直接用 AI 记事了');
  } catch (e) { toast(e.message); }
}

init(); ensureChatGreet(); loadHistory();

/* ============ 宿舍管理（床位视图） ============ */
let DORM = null;
async function loadDorm() {
  try {
    DORM = await api('/api/dorm');
    const st = DORM.stats;
    $('#dormSub').textContent = '宿舍 ' + st.rooms + ' 间（男 ' + st.male + ' · 女 ' + st.female + '） · 住宿 ' + st.residents + ' 人';
    const hy = DORM.hygiene || {};
    let h = '';
    DORM.rooms.forEach(r => {
      const recs = (hy[r.room] || []);
      let chip = '<span class="dl">未评分</span>';
      if (recs.length) {
        const avg = recs.reduce((a, x) => a + (x.score || 0), 0) / recs.length;
        chip = '<a class="hy-chip ' + (avg >= 9 ? 'good' : avg >= 7.5 ? 'mid' : 'bad') + '" onclick="event.stopPropagation();roomHy(\'' + esc(r.room) + '\')">卫生均分 ' + avg.toFixed(1) + ' ▾</a>';
      }
      h += '<div class="room-card">' +
        '<div class="rc-head">🛏️ <b>' + esc(r.room) + '</b>' +
        (r.gender ? '<span class="tag ' + (r.gender === '男' ? 'b' : 'r') + '">' + esc(r.gender) + '</span>' : '') +
        '<span class="grow-sp"></span><span class="ops">' +
        '<a title="编辑房间" onclick="roomForm(\'' + esc(r.room) + '\')">✎</a>' +
        '<a class="del" title="删除房间" onclick="delRoom(\'' + esc(r.room) + '\')">🗑</a></span></div>' +
        r.list.map(b => '<div class="bed' + (b.student_id ? '' : ' empty') + '" onclick="bedClick(\'' + esc(r.room) + '\',' + b.bed + ')"' +
          (b.name ? ' title="' + esc(b.name) + (b.gender ? ' · ' + b.gender : '') + '，点击可调整"' : ' title="空床，点击安排"') + '>' +
          '<span class="bn">' + b.bed + '号</span><span class="bname">' + esc(b.name || '空') + '</span></div>').join('') +
        '<div class="rc-foot">入住 ' + r.filled + '/' + r.beds + ' 人' +
        (r.building ? ' · ' + esc(r.building) + '栋' : '') + '<span class="grow-sp" style="flex:1"></span>' + chip + '</div></div>';
    });
    $('#dormRooms').innerHTML = h || '<div class="empty" style="grid-column:1/-1;padding:30px">还没有宿舍 — 点右上「＋ 新增宿舍」，或在花名册给学生填宿舍号自动建档</div>';
    const un = DORM.unassigned || [];
    $('#dormUnassignedCard').style.display = un.length ? '' : 'none';
    $('#dormUnassigned').innerHTML = un.map(n =>
      '<span class="tag y" style="cursor:pointer" onclick="unassignedPick(\'' + esc(n) + '\')">' + esc(n) + '</span>').join('') || '';
  } catch (e) { toast(e.message); }
}
function roomForm(room) {
  const r = room ? (DORM.rooms.find(x => x.room === room) || {}) : {};
  $('#mTitle').textContent = room ? '编辑宿舍 · ' + room : '新增宿舍';
  $('#mBody').innerHTML =
    '<div class="row mb"><label>房间号<input id="rmName" value="' + esc(room || '') + '" ' + (room ? 'disabled ' : '') + 'placeholder="如 A301"></label>' +
    '<label>楼栋<input id="rmBld" value="' + esc(r.building || '') + '" style="width:70px"></label>' +
    '<label>床位数<input id="rmBeds" type="number" value="' + (r.beds || 6) + '" min="1" max="12" style="width:70px"></label>' +
    '<label>性别<select id="rmGender"><option value="">混合</option>' +
    ['男', '女'].map(g => '<option' + (r.gender === g || (!r.gender && g === '男') ? ' selected' : '') + '>' + g + '</option>').join('') + '</select></label></div>' +
    (room ? '' : '<p class="hint">提示：花名册里宿舍号填了该房间的学生，保存后会自动入住排床。</p>') +
    '<div class="row" style="margin-top:12px"><button class="btn p" onclick="saveRoom(\'' + esc(room || '') + '\')">保存</button></div>';
  if (room) $('#rmName').disabled = true;
  $('#stuModal').style.display = 'flex';
}
async function saveRoom(orig) {
  const name = orig || $('#rmName').value.trim();
  if (!name) { toast('房间号必填'); return; }
  await post('/api/dorm/room', { room: name, building: $('#rmBld').value.trim(),
    beds: parseInt($('#rmBeds').value || '6'), gender: $('#rmGender').value });
  closeModal('stuModal'); toast('宿舍已保存 ✔'); loadDorm(); refreshHome();
}
async function delRoom(room) {
  if (!confirm('删除宿舍 ' + room + '？（有人在住时不允许删除）')) return;
  try {
    await post('/api/dorm/room/delete', { room });
    toast('已删除'); loadDorm();
  } catch (e) { toast(e.message, 5000); }
}
async function bedClick(room, bed) {
  const r = DORM.rooms.find(x => x.room === room); if (!r) return;
  const b = r.list[bed - 1];
  let h = '';
  if (b.student_id) {
    h += '<div class="row mb"><span style="font-size:15px"><b>' + esc(b.name) + '</b>' + (b.gender ? '（' + b.gender + '）' : '') + ' 现住 ' + room + ' ' + bed + '号床</span></div>';
    h += '<div class="row mb"><button class="btn danger" onclick="unassign(\'' + esc(room) + '\',' + bed + ',\'' + esc(b.student_id) + '\')">腾出该床</button></div><hr style="border:none;border-top:1px solid #eef1f6;margin:10px 0">';
  }
  h += '<p class="hint mb">选择学生入住本床（已在其他宿舍的学生会自动调寝）：</p>';
  const pool = DORM.rooms.flatMap(x => x.list.map(y => ({ name: y.name, sid: y.student_id, room: x.room })))
    .filter(x => x.sid).concat((DORM.unassigned || []).map(n => ({ name: n, sid: '', room: '' })));
  const all = await api('/api/students');
  const active = all.students.filter(x => x.status === '在校');
  h += '<div style="max-height:340px;overflow-y:auto">' + active.map(x => {
    const cur = (x.dorm || '').trim();
    return '<div class="bed" onclick="assignTo(\'' + esc(room) + '\',' + bed + ',\'' + esc(x.student_id) + '\')">' +
      '<span class="bn">' + esc(x.student_id) + '</span><span class="bname"><b>' + esc(x.name) + '</b></span>' +
      '<span class="dl">' + (cur === room ? '本房间' : cur ? cur : '未分') + '</span></div>';
  }).join('') + '</div>';
  $('#mTitle').textContent = room + ' · ' + bed + '号床';
  $('#mBody').innerHTML = h;
  $('#stuModal').style.display = 'flex';
}
async function assignTo(room, bed, sid) {
  try {
    const r = await post('/api/dorm/assign', { room, bed, student: sid });
    closeModal('stuModal'); toast(r.msg + ' ✔'); loadDorm();
  } catch (e) { toast(e.message); }
}
async function unassign(room, bed, sid) {
  try {
    const r = await post('/api/dorm/assign', { room, bed: 0, student: sid });
    closeModal('stuModal'); toast((r.msg || '已腾出床位') + ' ✔'); loadDorm();
  } catch (e) { toast(e.message); }
}
function unassignedPick(name) {
  const opts = DORM.rooms.flatMap(x => x.list.filter(b => !b.student_id).map(b => ({ room: x.room, bed: b.bed })));
  let h = '<p class="hint mb">为 <b>' + esc(name) + '</b> 选择一个空床位：</p>';
  h += opts.length ? opts.map(o => '<div class="bed" onclick="assignTo(\'' + esc(o.room) + '\',' + o.bed + ',\'' + esc(stuId(name)) + '\')"><span class="bn">' + esc(o.room) + '</span><span class="bname">' + o.bed + '号床</span></div>').join('')
    : '<div class="empty">暂无空床 — 先「＋新增宿舍」</div>';
  $('#mTitle').textContent = '安排宿舍 · ' + name;
  $('#mBody').innerHTML = h;
  $('#stuModal').style.display = 'flex';
}
function stuId(name) {
  const s = STUDENTS.find(x => x.name === name); return s ? s.student_id : name;
}
function hyForm() {
  $('#mTitle').textContent = '录入宿舍卫生检查';
  $('#mBody').innerHTML =
    '<div class="row mb"><label>房间<input id="dgRoom" list="roomList" placeholder="如 A301"><datalist id="roomList">' +
    (DORM ? DORM.rooms.map(r => '<option>' + esc(r.room) + '</option>').join('') : '') + '</datalist></label>' +
    '<label>日期<input type="date" id="dgDate" value="' + _dstr(new Date()) + '"></label>' +
    '<label>分数(0-10)<input id="dgScore" type="number" min="0" max="10" step="0.5" style="width:80px"></label></div>' +
    '<label>备注（扣分原因，可空）<input id="dgNote" class="grow" style="width:100%"></label>' +
    '<div class="row" style="margin-top:12px"><button class="btn p" onclick="addHygiene()">保存检查</button>' +
    '<span class="hint">同步计入班级文化→量化考核</span></div>';
  $('#stuModal').style.display = 'flex';
}
async function addHygiene() {
  const room = $('#dgRoom').value.trim();
  const score = parseFloat($('#dgScore').value);
  if (!room || isNaN(score)) { toast('房间与分数必填'); return; }
  const note = $('#dgNote').value.trim();
  const date = $('#dgDate').value;
  try {
    await post('/api/dorm/hygiene', { room, date, score, note });
    await post('/api/ledger/quant', { week: '卫生·' + room, hygiene: score, discipline: '', study: '', total: '',
      note: (note || '宿舍卫生检查') + '（' + date + '）' }).catch(() => { });
    closeModal('stuModal'); toast(room + ' ' + score + ' 分已记 ✔'); loadDorm();
  } catch (e) { toast(e.message); }
}
function roomHy(room) {
  const recs = ((DORM.hygiene || {})[room] || []);
  let h = '<p class="hint mb">' + room + ' 共 ' + recs.length + ' 条检查记录</p>' +
    recs.map(x => '<div class="srow"><span class="t">' + esc(x.date.slice(5)) + '</span>' +
      '<span class="x"><b>' + x.score + ' 分</b> ' + esc(x.note || '') + '</span>' +
      '<button class="btn sm" onclick="delHygiene(\'' + esc(room) + '\',\'' + x.uid + '\')">✕</button></div>').join('') ||
    '<div class="empty">暂无记录</div>';
  h += '<div class="row" style="margin-top:10px"><button class="btn p" onclick="hyForm()">＋ 再记一次检查</button></div>';
  $('#mTitle').textContent = '卫生记录 · ' + room;
  $('#mBody').innerHTML = h;
  $('#stuModal').style.display = 'flex';
}
async function delHygiene(room, uid) {
  await post('/api/dorm/hygiene/delete', { room, uid });
  await loadDorm();
  roomHy(room);
}
async function dormNotice() {
  try {
    const r = await post('/api/dorm/notice', {});
    $('#mTitle').textContent = '📢 宿舍卫生通报（草稿已存入通知中心）';
    $('#mBody').innerHTML = '<div class="dl" style="white-space:pre-wrap;font-size:13px;line-height:1.9">' + esc(r.text) + '</div>' +
      '<div class="row" style="margin-top:12px"><button class="btn p" onclick="navigator.clipboard.writeText(this.dataset.t).then(()=>toast(\'已复制，去粘贴到群 ✔\'))" data-t="' + esc(r.text).replace(/"/g, '&quot;') + '">📋 复制通报文本</button>' +
      '<button class="btn" onclick="closeModal(\'stuModal\')">关闭</button></div>';
    $('#stuModal').style.display = 'flex';
  } catch (e) { toast(e.message, 5000); }
}
/* 床位 / 评分 Excel 导入 */
$('#bedsFile') && $('#bedsFile').addEventListener('change', async e => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append('file', f);
  try {
    const r = await api('/api/dorm/import_beds', { method: 'POST', body: fd });
    toast('床位导入完成：成功 ' + r.ok + ' / ' + r.count + (r.failed.length ? ' · 失败：' + r.failed.slice(0, 3).join('；') : ' ✔'), 6000);
    loadDorm(); refreshHome();
  } catch (err) { toast('导入失败：' + err.message, 6000); }
  e.target.value = '';
});
$('#hyFile') && $('#hyFile').addEventListener('change', async e => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append('file', f);
  try {
    const r = await api('/api/dorm/hygiene_import', { method: 'POST', body: fd });
    toast('评分导入完成：' + r.ok + ' 条 ✔', 5000);
    loadDorm();
  } catch (err) { toast('导入失败：' + err.message, 6000); }
  e.target.value = '';
});

/* ============ 评优与评奖 ============ */
async function loadAwards() {
  try {
    const j = await api('/api/awards');
    const st = j.stats;
    let h = '<div class="hint mb">学期：' + esc(st.semester || '未设置') +
      (st.recent_exams ? ' · 已录入 ' + st.recent_exams + ' 场考试' : ' · 尚无成绩，名单按奖惩记录生成') + '</div>';
    if (st.rows && st.rows.length) {
      h += '<table class="t"><tr><th>排名</th><th>学号</th><th>姓名</th><th>综合得分率</th><th>建议等级</th><th>奖惩</th><th>备注</th></tr>' +
        st.rows.map((r, i) => '<tr><td>' + (i + 1) + '</td><td class="dl">' + esc(r.student_id || '') + '</td><td><b>' + esc(r.name) + '</b></td>' +
          '<td>' + (r.score == null ? '—' : r.score + '%') + '</td>' +
          '<td>' + (r.award ? '<span class="tag g">' + r.award + '</span>' : '—') + '</td>' +
          '<td>' + (r.honor_n ? '+' + r.honor_n : '') + ((st.punished || []).includes(r.name) ? '<span class="tag r">处分</span>' : '') + '</td>' +
          '<td class="dl">' + esc(r.note || '') + '</td></tr>').join('') + '</table>';
    } else h += '<div class="empty">暂无成绩数据 — 录入考试后自动生成奖学金预分名单</div>';
    $('#awardSuggest').innerHTML = h;
    $('#awardTable').innerHTML = '<tr><th>日期</th><th>类型</th><th>学生</th><th>名称</th><th></th></tr>' +
      j.records.map(a => '<tr><td>' + esc(a.date || '') + '</td><td><span class="tag ' + (a.type === '处分' ? 'r' : 'g') + '">' + esc(a.type) + '</span></td>' +
        '<td>' + esc(a.student) + '</td><td>' + esc(a.title || '') + '</td>' +
        '<td><button class="btn sm" onclick="delAward(\'' + a.uid + '\')">✕</button></td></tr>').join('') ||
      '<tr><td colspan="5" class="empty">暂无奖惩记录</td></tr>';
    const hs = st.honors || {};
    const names = Object.keys(hs);
    $('#honorSummary').innerHTML = names.length ? names.map(n =>
      '<div class="srow"><span class="t">🏅</span><span class="x"><b>' + esc(n) + '</b>：' + hs[n].map(a => esc(a.title)).join('、') + '</span></div>').join('')
      : '<div class="empty">暂无荣誉记录</div>';
  } catch (e) { toast(e.message); }
}
async function addAward() {
  if (!$('#avStu').value.trim() || !$('#avTitle').value.trim()) { toast('学生与名称必填'); return; }
  await post('/api/awards', { student: $('#avStu').value.trim(), type: $('#avType').value,
    title: $('#avTitle').value.trim(), date: $('#avDate').value });
  toast('已记录 ✔'); $('#avStu').value = ''; $('#avTitle').value = ''; loadAwards();
}
async function delAward(uid) { await post('/api/awards/' + uid + '/delete', {}); loadAwards(); }

/* ============ 扩展模块（自定义台账） ============ */
let EXT_MODS = [], EXT_CUR = '';
async function loadExt() {
  try {
    EXT_MODS = (await api('/api/ext')).modules || [];
    if (EXT_CUR && !EXT_MODS.some(m => m.id === EXT_CUR)) EXT_CUR = '';
    if (!EXT_CUR && EXT_MODS.length) EXT_CUR = EXT_MODS[0].id;
    const tabs = $('#extTabs');
    tabs.innerHTML = EXT_MODS.map(m =>
      '<span class="tag ' + (m.id === EXT_CUR ? 'b' : 'gr') + '" onclick="extSelect(\'' + m.id + '\')">' + esc(m.name) + '</span>').join('') +
      '<span class="tag g" onclick="extNewForm()">＋ 新建模块</span>';
    if (!EXT_MODS.length) { $('#extBody').innerHTML = '<div class="empty">还没有自定义模块 — 点「＋ 新建模块」，比如建一个「设备借用登记」「查寝记录」，自己定义字段即可开始记录</div>'; return; }
    const mod = EXT_MODS.find(m => m.id === EXT_CUR);
    let h = '<div class="row mb"><button class="btn p" onclick="extRecForm()">＋ 添加记录</button>' +
      '<button class="btn" onclick="extEditForm()">✎ 改字段</button>' +
      '<button class="btn danger" onclick="extDelModule()">删除模块</button></div>';
    const j = await api('/api/ledger/ext_' + mod.id);
    h += '<table class="t"><tr><th>时间</th>' + mod.fields.map(f => '<th>' + esc(f.label) + '</th>').join('') + '<th></th></tr>' +
      j.items.map(r => '<tr><td class="dl">' + esc((r.created_at || '').slice(5, 16)) + '</td>' +
        mod.fields.map(f => '<td>' + esc(r[f.key] != null ? r[f.key] : '') + '</td>').join('') +
        '<td><button class="btn sm" onclick="extDelRec(\'' + r.uid + '\')">✕</button></td></tr>').join('') ||
      '<tr><td colspan="' + (mod.fields.length + 2) + '" class="empty">暂无记录</td></tr></table>';
    $('#extBody').innerHTML = h;
  } catch (e) { toast(e.message); }
}
function extSelect(id) { EXT_CUR = id; loadExt(); }
function extNewForm() {
  window._EXT_NEW = true;   // 标记：本次保存是新建，不带 id（否则会覆盖当前选中模块）
  $('#mTitle').textContent = '新建扩展模块';
  $('#mBody').innerHTML = '<div class="row mb"><input id="mxName" placeholder="模块名称（如：设备借用）" style="width:200px"></div>' +
    '<div id="mxF" class="mb"></div><button class="btn" onclick="mxRow()">＋ 加字段</button>' +
    '<div class="row" style="margin-top:12px"><button class="btn p" onclick="extSaveModule()">创建</button></div>';
  mxRow();
  $('#stuModal').style.display = 'flex';
}
function mxRow() {
  const box = $('#mxF');
  const div = document.createElement('div');
  div.className = 'row mb';
  div.innerHTML = '<input placeholder="字段名" class="mxL grow">' +
    '<select class="mxT"><option value="text">文本</option><option value="number">数字</option><option value="date">日期</option></select>' +
    '<button class="btn sm" onclick="this.parentElement.remove()">✕</button>';
  box.appendChild(div);
}
async function extSaveModule() {
  const name = $('#mxName').value.trim();
  const fields = Array.from(document.querySelectorAll('#mxF .row')).map(r =>
    ({ label: r.querySelector('.mxL').value.trim(), type: r.querySelector('.mxT').value })).filter(f => f.label);
  if (!name || !fields.length) { toast('名称与至少一个字段必填'); return; }
  try {
    const body = { name, fields };
    if (EXT_CUR && !window._EXT_NEW) body.id = EXT_CUR;
    const r = await post('/api/ext', body);
    window._EXT_NEW = false; EXT_CUR = r.id; closeModal('stuModal'); toast('模块已保存 ✔'); loadExt();
  } catch (e) { toast(e.message); }
}
function extEditForm() {
  const mod = EXT_MODS.find(m => m.id === EXT_CUR); if (!mod) return;
  window._EXT_NEW = false;  // 编辑模式：保存时带上当前模块 id
  $('#mTitle').textContent = '修改模块：' + mod.name;
  $('#mBody').innerHTML = '<div class="row mb"><input id="mxName" value="' + esc(mod.name) + '" style="width:200px"></div>' +
    '<div id="mxF" class="mb">' + mod.fields.map(f =>
      '<div class="row mb"><input value="' + esc(f.label) + '" class="mxL grow">' +
      '<select class="mxT"><option value="text"' + (f.type === 'text' ? ' selected' : '') + '>文本</option>' +
      '<option value="number"' + (f.type === 'number' ? ' selected' : '') + '>数字</option>' +
      '<option value="date"' + (f.type === 'date' ? ' selected' : '') + '>日期</option></select>' +
      '<button class="btn sm" onclick="this.parentElement.remove()">✕</button></div>').join('') + '</div>' +
    '<button class="btn" onclick="mxRow()">＋ 加字段</button>' +
    '<div class="row" style="margin-top:12px"><button class="btn p" onclick="extSaveModule()">保存</button>' +
    '<span class="dl">改字段名不会迁移旧记录</span></div>';
  $('#stuModal').style.display = 'flex';
}
async function extDelModule() {
  if (!confirm('删除该自定义模块及其所有记录？')) return;
  await post('/api/ext/' + EXT_CUR + '/delete', {});
  EXT_CUR = ''; toast('已删除'); loadExt();
}
function extRecForm() {
  const mod = EXT_MODS.find(m => m.id === EXT_CUR); if (!mod) return;
  $('#mTitle').textContent = '添加记录 · ' + mod.name;
  $('#mBody').innerHTML = mod.fields.map(f =>
    '<label>' + esc(f.label) + '<input id="er_' + f.key + '" type="' +
    (f.type === 'number' ? 'number' : f.type === 'date' ? 'date' : 'text') + '"></label>').join('') +
    '<div class="row" style="margin-top:12px"><button class="btn p" onclick="extAddRec()">保存记录</button></div>';
  window._EXTMOD = mod;
  $('#stuModal').style.display = 'flex';
}
async function extAddRec() {
  const mod = window._EXTMOD; if (!mod) return;
  const payload = {};
  mod.fields.forEach(f => { payload[f.key] = $('#er_' + f.key).value.trim(); });
  if (!Object.values(payload).some(v => v)) { toast('至少填一个字段'); return; }
  await post('/api/ledger/ext_' + mod.id, payload);
  closeModal('stuModal'); toast('记录已添加 ✔'); loadExt();
}
async function extDelRec(uid) { await post('/api/ledger/ext_' + EXT_CUR + '/' + uid + '/delete', {}); loadExt(); }

/* ============ 课表：Excel 导入 / 文本粘贴 ============ */
async function importTimetableXlsx() {
  const f = document.getElementById('ttXlsxFile').files[0];
  if (!f) { toast('请先点「📂 选择课表 Excel」选择文件'); return; }
  $('#ttXlsxResult').innerHTML = '<span class="spin-inline"></span>正在理解课表（复杂格式走 AI，约十几秒）…';
  try {
    const fd = new FormData(); fd.append('file', f);
    const r = await api('/api/timetable/upload', { method: 'POST', body: fd });
    $('#ttXlsxResult').innerHTML = '<span style="color:var(--green)">✔ ' + r.method + '：' + r.count + ' 节课已写入课表' +
      (r.saved_path ? ' · 原件已存为「本学期课表」' : '') + '</span>';
    toast('课表导入成功（' + r.count + ' 节 · ' + r.method + '）✔', 5000);
    loadTimetable(); refreshHome();
  } catch (e) {
    $('#ttXlsxResult').innerHTML = '<span style="color:var(--red)">✗ ' + esc(e.message) + '</span>';
  }
}
async function wizardImportTimetable() {
  const f = document.getElementById('wTtFile').files[0];
  if (!f) { $('#wTtResult').textContent = '请先点「📂 选择课表 Excel」，或跳过稍后再导'; return; }
  $('#wTtResult').innerHTML = '<span class="spin-inline"></span>正在整理课表…';
  try {
    const fd = new FormData(); fd.append('file', f);
    const r = await api('/api/timetable/upload', { method: 'POST', body: fd });
    $('#wTtResult').innerHTML = '<span style="color:var(--green)">✔ 已导入 ' + r.count + ' 节课（' + r.method + '）</span>';
  } catch (e) {
    $('#wTtResult').innerHTML = '<span style="color:var(--red)">✗ ' + esc(e.message) + '</span>';
  }
}

/* ============ 帮助 ============ */
function mdToHtml(md) {
  const lines = md.split(/\r?\n/);
  let h = '', inUl = false;
  lines.forEach(l => {
    if (/^#{1,3} /.test(l)) {
      if (inUl) { h += '</ul>'; inUl = false; }
      const lv = l.match(/^#+/)[0].length;
      h += '<h' + lv + '>' + esc(l.replace(/^#+ /, '')) + '</h' + lv + '>';
    } else if (/^[-•] /.test(l)) {
      if (!inUl) { h += '<ul>'; inUl = true; }
      h += '<li>' + esc(l.replace(/^[-•] /, '')).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`(.+?)`/g, '<code>$1</code>') + '</li>';
    } else {
      if (inUl) { h += '</ul>'; inUl = false; }
      if (l.trim()) h += '<p>' + esc(l).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`(.+?)`/g, '<code>$1</code>') + '</p>';
    }
  });
  if (inUl) h += '</ul>';
  return h;
}
async function openHelp() {
  try {
    const j = await api('/api/help');
    $('#helpBody').innerHTML = '<div class="md-body">' + mdToHtml(j.markdown) + '</div>';
    $('#helpModal').style.display = 'flex';
  } catch (e) { toast(e.message); }
}
async function resetHelp() {
  if (!confirm('恢复默认帮助内容？你的修改将被覆盖。')) return;
  await post('/api/help/reset', {}); openHelp();
}

/* ============ AI 卡：服务商切换 ============ */
function aiProvToggle() {
  const prov = document.querySelector('input[name="aiProv"]:checked');
  if (!prov) return;
  const box = document.getElementById('aiCustomBox');
  if (box) box.style.display = prov.value === 'custom' ? '' : 'none';
}

/* 课表文件选择：显示所选文件名 */
[['ttXlsxFile', 'ttXlsxName'], ['wTtFile', 'wTtName']].forEach(([fid, nid]) => {
  const el = document.getElementById(fid);
  if (el) el.addEventListener('change', () => {
    const f = el.files[0];
    const nameEl = document.getElementById(nid);
    if (nameEl) nameEl.textContent = f ? '已选：' + f.name : '未选择文件';
  });
});

/* ============ 表格自适应：自动包裹横向滚动容器 ============ */
function wrapTables(root) {
  (root || document).querySelectorAll('table.t').forEach(t => {
    const p = t.parentElement;
    if (!p || p.classList.contains('tw')) return;
    const w = document.createElement('div');
    w.className = 'tw';
    p.insertBefore(w, t);
    w.appendChild(t);
  });
}
/* 只有表头、没有数据行的表格 → 自动补一行「暂无记录」 */
function fixEmptyTables() {
  document.querySelectorAll('table.t').forEach(t => {
    const rows = t.querySelectorAll('tr');
    if (rows.length !== 1) return;
    const head = rows[0];
    if (!head.querySelector('th') || head.querySelector('td')) return;
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = head.querySelectorAll('th').length;
    td.className = 'empty';
    td.textContent = '暂无记录';
    tr.appendChild(td);
    t.appendChild(tr);
  });
}
let _twScheduled = false;
new MutationObserver(() => {
  if (_twScheduled) return;
  _twScheduled = true;
  requestAnimationFrame(() => {
    _twScheduled = false;
    wrapTables(document);
    fixEmptyTables();
  });
}).observe(document.body, { childList: true, subtree: true });
wrapTables(document);
fixEmptyTables();
