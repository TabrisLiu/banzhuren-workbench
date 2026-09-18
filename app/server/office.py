# -*- coding: utf-8 -*-
"""办公文档层：Excel 读写(openpyxl) + Word 生成(python-docx) + 图片存储。"""
import os
import uuid
from datetime import datetime

from docx import Document
from docx.shared import Pt
from openpyxl import Workbook, load_workbook

from . import data, store

# 花名册导入列名映射：中文列头关键字 -> 字段
ROSTER_HEADER_MAP = [
    (("学号", "学籍号", "考生号", "准考证号"), "student_id"),
    (("姓名",), "name"),
    (("性别",), "gender"),
    (("出生", "生日", "出生年月"), "birth"),
    (("生源", "籍贯", "省份", "民族地区"), "origin"),
    (("专业",), "major"),
    (("班级",), "class_name"),
    (("宿舍", "寝室", "房间"), "dorm"),
    (("家长", "父亲", "母亲", "监护人", "联系人", "户主"), "parent_name"),
    (("电话", "手机", "联系", "联系方式"), "parent_phone"),
    (("住址", "地址", "家庭"), "address"),
    (("备注", "说明"), "remark"),
]


# 家长名单列名识别。家长/学生姓名极易混淆，判定顺序固定为：电话 > 关系 > 姓名 > 学号
_PHONE_KEYS = ("电话", "手机", "号码", "联系方式")
_REL_KEYS = ("关系", "称谓")
_NAME_KEYS = ("姓名", "名字", "称呼")
_PARENT_KEYS = ("父亲", "母亲", "爸爸", "妈妈", "家长", "监护人", "户主", "联系人")
_STUDENT_KEYS = ("学生", "孩子", "本人")
_ID_KEYS = ("学号", "学籍", "考号", "准考证", "编号")

# 同一字段出现第二列时（如「父亲电话」「母亲电话」），落到第二联系人槽位
SECOND_SLOT = {"parent_name": "parent_name2", "parent_relation": "parent_relation2",
               "parent_phone": "parent_phone2"}


def _classify_parent_header(text):
    t = _norm(text)
    if not t:
        return None
    is_phone = any(k in t for k in _PHONE_KEYS)
    is_rel = any(k in t for k in _REL_KEYS)
    is_parent = any(k in t for k in _PARENT_KEYS)
    is_student = any(k in t for k in _STUDENT_KEYS)
    if is_phone:
        return "parent_phone"          # 家长名单里的电话列默认就是监护人联系方式
    if is_rel:
        return "parent_relation"
    if any(k in t for k in _NAME_KEYS):
        return "parent_name" if is_parent else "name"
    if any(k in t for k in _ID_KEYS):
        return "student_id"
    if is_parent:
        return "parent_name"
    if is_student:
        return "name"
    return None


def _map_parent_headers(row_vals):
    """返回 {col_index: field}；命中学生标识 + 家长信息各至少一列才算有效表头。"""
    m, taken = {}, set()
    for i, cell in enumerate(row_vals):
        field = _classify_parent_header(cell)
        if not field:
            continue
        slot = field
        if field in taken:
            slot = SECOND_SLOT.get(field)
            if not slot or slot in taken:
                continue
        m[i] = slot
        taken.add(field)
        taken.add(slot)
    has_stu = "student_id" in m.values() or "name" in m.values()
    has_par = any(v.startswith("parent_") for v in m.values())
    return m if (has_stu and has_par) else {}


def parse_parent_xlsx(path):
    """解析家长名单 Excel（.xlsx/.xlsm/.xls）。返回 (rows, meta)。"""
    grid = _load_sheet_rows(path)
    header_map, header_row_idx, rows, raw_headers = {}, -1, [], []
    for ri, row in enumerate(grid[:20], start=1):
        m = _map_parent_headers(row)
        if m:
            header_map, header_row_idx = m, ri
            raw_headers = [_norm(c) for c in row]
            break
    if not header_map:
        first_row = []
        for row in grid[:10]:
            vals = [_norm(c) for c in row if _norm(c)]
            if vals:
                first_row = vals
                break
        return [], {"error": "未识别到表头", "first_row": first_row}
    for row in grid[header_row_idx:]:
        rec = {}
        for ci, field in header_map.items():
            if ci >= len(row):
                continue
            val = row[ci]
            if field.endswith("phone") or field == "parent_phone2":
                val = _clean_phone(val)
            elif field == "student_id":
                val = _norm(val).split(".")[0]
            else:
                val = _norm(val)
            if val:
                rec[field] = val
        if not (rec.get("student_id") or rec.get("name")):
            continue
        if not any(rec.get(f) for f in ("parent_name", "parent_phone", "parent_name2", "parent_phone2")):
            continue
        # 列名形如「父亲姓名」「母亲电话」时，自动补出与学生的关系，省得手工填
        for name_f, rel_f in (("parent_name", "parent_relation"), ("parent_name2", "parent_relation2")):
            if not rec.get(name_f):
                continue
            ci = next((c for c, f in header_map.items() if f == name_f), None)
            head = raw_headers[ci] if (ci is not None and ci < len(raw_headers)) else ""
            for kw, rel in (("父亲", "父亲"), ("爸爸", "父亲"), ("母亲", "母亲"), ("妈妈", "母亲"),
                            ("祖父", "祖父"), ("祖母", "祖母"), ("外公", "外公"), ("外婆", "外婆")):
                if kw in head:
                    rec[rel_f] = rel
                    break
        rows.append(rec)
    return rows, {"headers": raw_headers, "header_row": header_row_idx,
                  "matched": sorted(set(header_map.values()))}


def export_parents_xlsx(class_id, path, ledger=None):
    """导出家长名单（含沟通统计）。ledger: 家校沟通台账记录列表。"""
    ss = sorted(store.students(class_id), key=lambda s: s.get("student_id", ""))
    last, cnt = {}, {}
    for r in (ledger or []):
        nm = (r.get("student") or "").strip()
        if not nm:
            continue
        d = r.get("date") or (r.get("created_at") or "")[:10]
        if d and d > last.get(nm, ""):
            last[nm] = d
        cnt[nm] = cnt.get(nm, 0) + 1
    headers = ["学号", "姓名", "家长姓名", "与学生关系", "联系电话",
               "第二联系人", "关系", "联系电话2", "最近沟通", "沟通次数"]
    wb = Workbook()
    ws = wb.active
    ws.title = "家长名单"
    ws.append(headers)
    for s in ss:
        nm = s.get("name", "")
        ws.append([s.get("student_id", ""), nm, s.get("parent_name", ""),
                   s.get("parent_relation", ""), s.get("parent_phone", ""),
                   s.get("parent_name2", ""), s.get("parent_relation2", ""),
                   s.get("parent_phone2", ""), last.get(nm, ""), cnt.get(nm, 0)])
    for i, w in enumerate([14, 10, 12, 10, 15, 12, 10, 15, 12, 8], start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    wb.save(path)
    return path


def export_parents_template(class_id, path):
    """导出家长名单导入模板：预填现有学生学号/姓名，家长栏留空供填写。"""
    ss = sorted(store.students(class_id), key=lambda s: s.get("student_id", ""))
    wb = Workbook()
    ws = wb.active
    ws.title = "家长名单"
    ws.append(["学号", "姓名", "家长姓名", "与学生关系", "联系电话"])
    for s in ss:
        ws.append([s.get("student_id", ""), s.get("name", ""),
                   s.get("parent_name", ""), s.get("parent_relation", ""), s.get("parent_phone", "")])
    ws.append([])
    ws.append(["填写说明：学号和姓名至少填一列（用于匹配学生）；关系可填 父亲/母亲/祖父/其他；"
               "同一学生有两位监护人时，可再填一列「第二联系人」或另起一行。"])
    for i, w in enumerate([14, 10, 12, 12, 15], start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    wb.save(path)
    return path


def _norm(s):
    return str(s).strip() if s is not None else ""


def _map_headers(row_vals):
    """给定一行单元格值，返回 {col_index: field}，命中 ≥3 列才视为表头。"""
    m = {}
    for i, cell in enumerate(row_vals):
        text = _norm(cell)
        if not text:
            continue
        for keys, field in ROSTER_HEADER_MAP:
            if field in m.values():
                continue
            if any(k in text for k in keys):
                m[i] = field
                break
    return m if len(m) >= 3 else {}


def _clean_phone(v):
    s = _norm(v)
    return s.replace(".0", "").replace(" ", "") if s else ""




def _cell(v):
    if v is None or v == "":
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def _load_sheet_rows(path):
    """Read first sheet as list[list[str]]. Supports .xlsx/.xlsm and .xls."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xls":
        import xlrd
        book = xlrd.open_workbook(path)
        ws = book.sheet_by_index(0)
        rows = []
        for r in range(ws.nrows):
            line = []
            for c in range(ws.ncols):
                cell = ws.cell(r, c)
                v = cell.value
                if cell.ctype == xlrd.XL_CELL_DATE and v:
                    v = xlrd.xldate_as_datetime(v, book.datemode).strftime("%Y-%m-%d")
                line.append(_cell(v))
            rows.append(line)
        return rows
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb.active
    rows = [[_cell(c) for c in r] for r in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


def parse_roster_xlsx(path):
    """解析花名册 Excel，自动找表头行。返回 (rows, meta)。"""
    grid = _load_sheet_rows(path)
    header_map, header_row_idx, rows, raw_headers = {}, -1, [], []
    for ri, row in enumerate(grid[:20], start=1):
        m = _map_headers(row)
        if m:
            header_map, header_row_idx = m, ri
            raw_headers = [_norm(c) for c in row]
            break
    if not header_map:
        first_row = []
        for row in grid[:10]:
            vals = [_norm(c) for c in row if _norm(c)]
            if vals:
                first_row = vals
                break
        return [], {"error": "未识别到表头", "first_row": first_row}
    for row in grid[header_row_idx:]:
        rec = {}
        for ci, field in header_map.items():
            if ci < len(row):
                val = row[ci]
                if field == "parent_phone":
                    val = _clean_phone(val)
                elif field == "birth":
                    val = _norm(val).replace("/", "-").replace(".", "-")
                elif field == "student_id":
                    val = _norm(val).split(".")[0]
                else:
                    val = _norm(val)
                if val:
                    rec[field] = val
        if rec.get("student_id") and rec.get("name"):
            rows.append(rec)
    return rows, {"headers": raw_headers, "header_row": header_row_idx,
                  "matched": sorted(header_map.values())}


def export_roster_xlsx(class_id, path):
    ss = sorted(store.students(class_id), key=lambda s: s.get("student_id", ""))
    tags = store.get_tags(class_id)
    tag_names = {v: k for k, v in store.TAG_LABELS.items()}
    headers = ["学号", "姓名", "性别", "出生日期", "生源省份", "专业", "班级",
               "宿舍", "家长姓名", "联系电话", "家庭住址", "学籍状态", "标签", "备注"]
    wb = Workbook()
    ws = wb.active
    ws.title = "花名册"
    ws.append(headers)
    for s in ss:
        tlist = [tag_names.get(t, t) for t in tags.get(s.get("student_id"), [])]
        ws.append([s.get("student_id", ""), s.get("name", ""), s.get("gender", ""),
                   s.get("birth", ""), s.get("origin", ""), s.get("major", ""),
                   s.get("class_name", ""), s.get("dorm", ""), s.get("parent_name", ""),
                   s.get("parent_phone", ""), s.get("address", ""), s.get("status", ""),
                   "、".join(tlist), s.get("remark", "")])
    widths = [12, 10, 6, 12, 12, 18, 10, 8, 10, 13, 28, 10, 18, 18]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i) if i <= 26 else "A" + chr(64 + i - 26)].width = w
    wb.save(path)
    return path


def export_todos_xlsx(class_id, path, today=None):
    ls = store.list_todos(class_id, today)
    wb = Workbook()
    ws = wb.active
    ws.title = "待办"
    ws.append(["状态", "标题", "截止", "时间", "分类", "优先级", "来源", "创建时间"])
    bucket_cn = {"overdue": "已逾期", "today": "今日", "todo": "未完成", "done": "已完成"}
    for t in ls:
        ws.append([bucket_cn.get(t.get("bucket"), ""), t.get("title", ""),
                   t.get("due", ""), t.get("time", ""), t.get("category", ""),
                   t.get("priority", ""), t.get("source", ""), t.get("created_at", "")])
    for i, w in enumerate([8, 34, 12, 8, 12, 8, 10, 18], start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    wb.save(path)
    return path


def export_attendance_xlsx(class_id, path, date_str):
    a = store.attendance_on(class_id, date_str)
    by_sid = {s["student_id"]: s for s in store.students(class_id)}
    wb = Workbook()
    ws = wb.active
    ws.title = "考勤"
    ws.append(["日期", "学号", "姓名", "状态", "备注"])
    for x in a["leave"]:
        ws.append([date_str, x["student_id"], x["name"], "请假", x.get("type", "")])
    for x in a["absent"]:
        ws.append([date_str, x["student_id"], x["name"], "旷课", ""])
    for x in a["late"]:
        ws.append([date_str, x["student_id"], x["name"], x["mark"], ""])
    for sid in by_sid:
        if sid not in {y["student_id"] for y in a["leave"] + a["absent"] + a["late"]}:
            ws.append([date_str, sid, by_sid[sid].get("name", ""), "正常", ""])
    for i, w in enumerate([12, 12, 10, 8, 14], start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    wb.save(path)
    return path


# ---------- Word ----------

WEEK_DAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]



def _parse_timetable_week_matrix(rows):
    """教务系统"周矩阵"课表：列=周次(表头含 第N周)，行=星期×节次。
    同一(星期,节次,课程,教室)的连续周次自动合并为区间。返回 entries；非此版式返回 None。"""
    import re as _re
    hrow, colmap = -1, {}
    for ri, row in enumerate(rows[:8]):
        m = {}
        for ci, cell in enumerate(row):
            mm = _re.match(r"^\s*第(\d+)周", cell or "")
            if mm:
                m[ci] = int(mm.group(1))
        if len(m) >= 4:
            hrow, colmap = ri, m
            break
    if hrow < 0:
        return None

    def norm_period(t):
        t = _re.sub(r"\s", "", t)
        if "晚" in t:
            return "晚自习"
        mm = _re.search(r"(\d+)[-~至](\d+)节?", t)
        if mm:
            return "%s-%s节" % (mm.group(1), mm.group(2))
        mm = _re.match(r"^(\d+)节?", t)
        if mm:
            return "%s-%s节" % (mm.group(1), mm.group(1))
        return ""

    entries = {}   # (wd, period, course, room) -> [weeks]
    wd = ""
    for row in rows[hrow + 1:]:
        c0 = (row[0] if row else "").strip()
        if _re.match(r"^周[一二三四五六日]$", c0):
            wd = c0
        period = ""
        for cell in row[1:4]:
            p = norm_period(cell or "")
            if p:
                period = p
                break
        if not wd or not period:
            continue
        for ci, wk in colmap.items():
            if ci >= len(row):
                continue
            cell = (row[ci] or "").strip()
            if not cell or cell in ("-", "/"):
                continue
            parts = [p.strip() for p in _re.split(r"[\r\n｜|]+", cell) if p.strip()]
            if not parts:
                continue
            course = parts[0]
            room = teacher = ""
            for extra in parts[1:]:
                if not room and any(k in extra for k in ("#", "楼", "室", "训", "中心", "车间", "基地", "工厂")):
                    room = extra
                elif not teacher and len(extra) <= 6 and not any(ch.isdigit() for ch in extra):
                    teacher = extra
            entries.setdefault((wd, period, course, room, teacher), []).append(wk)

    out = []
    for (w, period, course, room, teacher), weeks in entries.items():
        weeks = sorted(set(weeks))
        segs, start, prev = [], weeks[0], weeks[0]
        for x in weeks[1:]:
            if x == prev + 1:
                prev = x
                continue
            segs.append((start, prev))
            start = prev = x
        segs.append((start, prev))
        for a, b in segs:
            wk_s = "%d-%d" % (a, b) if a != b else str(a)
            out.append({"weekday": w, "period": period, "course": course,
                        "room": room, "teacher": teacher, "odd": "all", "weeks": wk_s})
    return out or None


def parse_timetable_xlsx(path):
    """规则解析课表 Excel：找含 周一.. 的表头行，首列为节次，逐格提取课程。
    单元格文本支持"高等数学 3-14周 单周"混排。返回 entries；解析失败 raise。"""
    import re as _re
    rows = _load_sheet_rows(path)
    m = _parse_timetable_week_matrix(rows)
    if m:
        return m
    header_idx, colmap = -1, {}
    for ri, row in enumerate(rows[:8]):
        m = {}
        for ci, cell in enumerate(row):
            t = cell.replace("星期", "周")
            for w in WEEK_DAYS:
                if t == w or t.startswith(w):
                    m[ci] = w
                    break
        if len(m) >= 3:
            header_idx, colmap = ri, m
            break
    if header_idx < 0:
        raise ValueError("未识别到课表表头（需含 周一~周五 等列）")
    entries = []
    for row in rows[header_idx + 1:]:
        period = ""
        for cell in row[:2]:
            t = _norm(cell)
            if t and ("节" in t or "晚" in t or _re.match(r"^\d", t)):
                period = t if "节" in t or "晚" in t else t + "节"
                break
        if not period:
            continue
        for ci, w in colmap.items():
            if ci >= len(row):
                continue
            cell = _norm(row[ci])
            if not cell or cell in ("-", "/", "无"):
                continue
            odd, weeks = "all", ""
            mm = _re.search(r"(\d+)\s*[-~至]\s*(\d+)\s*周", cell)
            if mm:
                weeks = "%s-%s" % (mm.group(1), mm.group(2))
            if "单周" in cell:
                odd = "odd"
            elif "双周" in cell:
                odd = "even"
            course = _re.sub(r"[\s,，]*\d+\s*[-~至]\s*\d+\s*周(次)?", "", cell)
            course = course.replace("单周", "").replace("双周", "").strip() or cell
            period = _re.sub(r"^第", "", period).strip()
            entries.append({"weekday": w, "period": period, "course": course,
                            "odd": odd, "weeks": weeks})
    if not entries:
        raise ValueError("表头识别成功但未提取到课程格")
    return entries


def timetable_raw_text(path, max_rows=40, max_cols=12):
    """把课表 Excel 原样转成制表符文本，供 AI 兜底理解。"""
    grid = _load_sheet_rows(path)
    lines = []
    for r in grid[:max_rows]:
        cells = [_norm(c).replace("\n", " ") for c in r[:max_cols]]
        if any(cells):
            lines.append("\t".join(cells))
    return "\n".join(lines)


def _doc_header(doc, title, subtitle=""):
    h = doc.add_heading(title, level=0)
    if subtitle:
        p = doc.add_paragraph(subtitle)
        p.runs[0].font.size = Pt(9)


def export_student_word(class_id, sid, path):
    s = store.get_student(class_id, sid)
    if not s:
        return None
    doc = Document()
    _doc_header(doc, "学生成长档案（一生一档）",
                "班主任工作台生成 · %s" % data.now_str())
    tags = store.get_tags(class_id).get(s.get("student_id"), [])
    tag_cn = [store.TAG_LABELS.get(t, t) for t in tags]
    doc.add_heading("一、基本信息", level=1)
    tbl = doc.add_table(rows=0, cols=2)
    tbl.style = "Light Grid Accent 1"
    info = [("学号", s.get("student_id")), ("姓名", s.get("name")),
            ("性别", s.get("gender")), ("出生日期", s.get("birth")),
            ("生源省份", s.get("origin")), ("专业", s.get("major")),
            ("班级", s.get("class_name")), ("宿舍", s.get("dorm")),
            ("家长", "%s %s" % (s.get("parent_name", ""), s.get("parent_phone", ""))),
            ("家庭住址", s.get("address")), ("学籍状态", s.get("status")),
            ("标签", "、".join(tag_cn)), ("备注", s.get("remark"))]
    for k, v in info:
        row = tbl.add_row()
        row.cells[0].text = k
        row.cells[1].text = _norm(v)
    doc.add_heading("二、请假记录", level=1)
    leaves = [x for x in store.list_leaves(class_id) if x.get("student") == s.get("name")]
    if leaves:
        for x in leaves:
            doc.add_paragraph("• %s～%s %s %s（%s）" % (
                x.get("start_date", ""), x.get("end_date", ""), x.get("type", ""),
                x.get("reason", ""), x.get("status", "")), style="List Bullet")
    else:
        doc.add_paragraph("暂无")
    doc.add_heading("三、预警记录", level=1)
    warns = [w for w in data.records("warnings", class_id)
             if w.get("student") == s.get("name")]
    if warns:
        for w in warns:
            doc.add_paragraph("• [%s·%s] %s（%s）" % (
                w.get("level", ""), w.get("kind", ""), w.get("desc", ""),
                w.get("created_at", "")), style="List Bullet")
    else:
        doc.add_paragraph("暂无")
    doc.save(path)
    return path


def export_summary_word(class_id, path):
    """班级整体画像 Word：花名册统计 + 请假 + 待办 + 预警。"""
    cfg = data.load_config()
    cls = cfg["class"]
    ss = store.students(class_id)
    st = store.roster_stats(class_id)
    tags = store.get_tags(class_id)
    counts = {}
    for lst in tags.values():
        for t in lst:
            counts[store.TAG_LABELS.get(t, t)] = counts.get(store.TAG_LABELS.get(t, t), 0) + 1
    doc = Document()
    _doc_header(doc, "班级情况汇总",
                "%s %s ｜ 生成于 %s" % (cls.get("name", ""), cls.get("major", ""), data.now_str()))
    doc.add_heading("一、花名册概览", level=1)
    doc.add_paragraph("在册 %d 人（在校 %d 人，男 %d / 女 %d）" % (
        st["total"], st["active"], st["male"], st["female"]))
    if st["inactive"]:
        doc.add_paragraph("非在校：" + "、".join(
            "%s(%s)" % (x["name"], x["status"]) for x in st["inactive"]))
    doc.add_heading("二、标签分布", level=1)
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        doc.add_paragraph("• %s：%d 人" % (k, v), style="List Bullet")
    doc.add_heading("三、请假记录（近期）", level=1)
    leaves = store.list_leaves(class_id)[:10]
    for x in leaves:
        doc.add_paragraph("• %s %s %s～%s %s（%s）" % (
            x.get("student", ""), x.get("type", ""), x.get("start_date", ""),
            x.get("end_date", ""), x.get("reason", ""), x.get("status", "")),
            style="List Bullet")
    if not leaves:
        doc.add_paragraph("暂无")
    doc.add_heading("四、当前预警", level=1)
    warns = store.list_warnings(class_id)
    for w in warns:
        doc.add_paragraph("• [%s] %s · %s：%s" % (
            w.get("level", ""), w.get("kind", ""), w.get("student", ""), w.get("desc", "")),
            style="List Bullet")
    if not warns:
        doc.add_paragraph("暂无")
    doc.add_heading("五、待办概览", level=1)
    today = data.today_str()
    tc = store.count_todos(class_id, today)
    doc.add_paragraph("已逾期 %d ｜ 今日 %d ｜ 未完成 %d" % (
        tc["overdue"], tc["today"], tc["todo"]))
    for t in store.list_todos(class_id, today)[:8]:
        if t["bucket"] in ("overdue", "today"):
            doc.add_paragraph("• [%s] %s（%s）" % (
                {"overdue": "逾期", "today": "今日"}[t["bucket"]],
                t.get("title", ""), t.get("due", "")), style="List Bullet")
    doc.save(path)
    return path



def export_dorm_xlsx(view, path):
    """宿舍床位表：房间/楼栋/性别/床号/学号/姓名。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "宿舍分配"
    ws.append(["房间", "楼栋", "性别", "床号", "学号", "姓名"])
    for r in view["rooms"]:
        for b in r["list"]:
            ws.append([r["room"], r.get("building", ""), r.get("gender", ""),
                       b["bed"], b["student_id"], b["name"] or "空"])
    for i, w in enumerate([10, 6, 6, 6, 14, 12], start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    wb.save(path)
    return path


def export_grade_report_docx(class_id, rep, path):
    """学业分析完整报告 Word。"""
    doc = Document()
    k = rep["kpi"]
    _doc_header(doc, "学业分析报告 · %s" % rep["exam"],
                "考试日期 %s ｜ 参考 %d 人 ｜ %d 个科目" % (rep.get("date") or "", k["count"], k["subjects"]))
    doc.add_heading("一、总体指标", level=1)
    t = doc.add_table(rows=0, cols=2); t.style = "Light Grid Accent 1"
    for label, val in [("班级平均总分", k["avg_total"]), ("满分合计", k["full_total"]),
                       ("最高 / 最低", "%s / %s" % (k["max_total"], k["min_total"])),
                       ("极差", k["range"]), ("平均得分率", "%s%%" % k["avg_ratio"]),
                       ("优良率(A+B)", "%d 人" % k["tier_good"])]:
        row = t.add_row(); row.cells[0].text = label; row.cells[1].text = str(val)
    doc.add_heading("二、各学科情况", level=1)
    t2 = doc.add_table(rows=1, cols=6); t2.style = "Light Grid Accent 1"
    for i, h in enumerate(["科目", "满分", "平均分", "最高", "最低", "及格率"]):
        t2.rows[0].cells[i].text = h
    for s in rep["subjects"]:
        row = t2.add_row()
        for i, v in enumerate([s["subject"], s["full"], s["avg"], s["max"], s["min"], "%s%%" % s["pass_rate"]]):
            row.cells[i].text = str(v)
    doc.add_heading("三、关注学科（平均分最低）", level=1)
    for f in rep["focus"]:
        doc.add_paragraph("• %s：平均 %s / %s，及格率 %s%%，不及格 %d 人" % (
            f["subject"], f["avg"], f["full"], f["pass_rate"], f["failed_n"]), style="List Bullet")
    doc.add_heading("四、总分前列（前 10）", level=1)
    for d in rep["top"]:
        doc.add_paragraph("• 第 %d 名 %s：%s 分（得分率 %s%%）" % (d["rank"], d["name"], d["total"], d["ratio"]),
                          style="List Bullet")
    if rep.get("failed_students"):
        doc.add_heading("五、不及格明细", level=1)
        names = {}
        for x in rep["failed_students"]:
            names.setdefault(x["name"], []).append("%s %s" % (x["subject"], x["score"]))
        for name, items in names.items():
            doc.add_paragraph("• %s：%s" % (name, "、".join(items)), style="List Bullet")
    if rep.get("up") or rep.get("down"):
        doc.add_heading("六、与上次考试对比", level=1)
        if rep["up"]:
            doc.add_paragraph("进步：" + "、".join("%s(+%s)" % (u["name"], u["delta"]) for u in rep["up"]))
        if rep["down"]:
            doc.add_paragraph("退步：" + "、".join("%s(%s)" % (u["name"], u["delta"]) for u in rep["down"]))
    doc.save(path)
    return path


# ---------- 图片 ----------

IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


def save_image(content: bytes, original_name: str, category="misc"):
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in IMG_EXT:
        ext = ".png"
    d = os.path.join(data.PHOTO_DIR, category)
    os.makedirs(d, exist_ok=True)
    fname = "%s_%s%s" % (datetime.now().strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:6], ext)
    path = os.path.join(d, fname)
    with open(path, "wb") as f:
        f.write(content)
    return path
