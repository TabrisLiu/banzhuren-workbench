# -*- coding: utf-8 -*-
"""业务逻辑层：学生/花名册/请假/考勤/待办/通知/日程/预警。所有模块通过 student_id 联动。"""
from datetime import datetime, timedelta

from . import data

STUDENT_FIELDS = [
    "student_id", "name", "gender", "birth", "origin", "major", "class_name",
    "dorm", "parent_name", "parent_relation", "parent_phone",
    "parent_name2", "parent_relation2", "parent_phone2",
    "address", "status", "remark",
]

# 家长信息字段（导入家长名单时只写这些字段，不碰学籍等其他信息）
PARENT_FIELDS = ["parent_name", "parent_relation", "parent_phone",
                 "parent_name2", "parent_relation2", "parent_phone2"]

STATUS_ACTIVE = "在校"
STATUS_INACTIVE = {"休学", "退学", "毕业", "参军", "其他"}

# 标签中文名（tags 数据文件: {class_id: {student_id: [tag,...]}}）
TAG_LABELS = {
    "liushou": "留守", "danqin": "单亲", "xuekun": "学困", "tuishi": "退役士兵",
    "jiandang": "建档立卡", "xinli": "心理关注", "banwei": "班委", "jingxuan": "竞赛",
    "qinjian": "全勤", "pianke": "偏科", "linjie": "临界",
}


def students(class_id):
    return data.records("students", class_id)


def get_student(class_id, sid):
    for s in students(class_id):
        if s.get("student_id") == sid or s.get("name") == sid:
            return s
    return None


def get_tags(class_id):
    obj = data.get_obj("tags", {}) or {}
    return obj.get(class_id, {})


def set_tag(class_id, sid, tag, on=True):
    obj = data.get_obj("tags", {}) or {}
    m = obj.setdefault(class_id, {})
    lst = m.setdefault(sid, [])
    if on and tag not in lst:
        lst.append(tag)
    elif not on and tag in lst:
        lst.remove(tag)
    data.set_obj("tags", obj, "tag")


def upsert_student(class_id, payload, source="manual"):
    """按学号新增或更新学生。返回 (student, created)。"""
    sid = str(payload.get("student_id") or "").strip()
    if not sid:
        return None, False
    for s in students(class_id):
        if s.get("student_id") == sid:
            patch = {k: v for k, v in payload.items() if v not in (None, "")}
            r = data.update("students", s["uid"], patch, class_id, source)
            return r, False
    rec = {k: payload.get(k, "") for k in STUDENT_FIELDS}
    rec["student_id"] = sid
    rec["status"] = payload.get("status") or STATUS_ACTIVE
    r = data.insert("students", rec, class_id, source)
    return r, True


def import_roster(class_id, rows, source="import"):
    """rows: [{student_id,name,...}]。按学号 upsert；返回统计。"""
    created, updated = 0, 0
    for row in rows:
        s, c = upsert_student(class_id, row, source)
        if c:
            created += 1
        elif s:
            updated += 1
    return {"created": created, "updated": updated, "total": len(rows)}


def _norm_key(v):
    return str(v or "").strip().replace(" ", "").replace("\u3000", "")


def import_parents(class_id, rows, source="import"):
    """导入家长名单。rows: [{student_id|name, parent_name, parent_relation, parent_phone,
    parent_name2, parent_relation2, parent_phone2}]

    按学号优先、姓名兜底匹配已有学生；只覆盖家长信息字段，绝不动学籍/宿舍等其他内容。
    同名学生（如父母各一行）会依次写入第一、第二联系人。
    """
    ss = students(class_id)
    by_sid, by_name = {}, {}
    for s in ss:
        sid = _norm_key(s.get("student_id"))
        if sid:
            by_sid.setdefault(sid, s)
        nm = _norm_key(s.get("name"))
        if nm:
            by_name.setdefault(nm, s)

    updated, unchanged, skipped, unmatched = 0, 0, 0, []
    for row in rows:
        sid = _norm_key(row.get("student_id"))
        nm = _norm_key(row.get("name"))
        s = by_sid.get(sid) if sid else None
        if s is None and nm:
            s = by_name.get(nm)
        if not s:
            unmatched.append({"student_id": row.get("student_id") or "", "name": row.get("name") or "",
                              "parent_name": row.get("parent_name") or ""})
            continue
        # 第一联系人已存在且本次姓名不同 → 写入第二联系人
        cur1 = _norm_key(s.get("parent_name"))
        new1 = _norm_key(row.get("parent_name"))
        into_second = bool(cur1 and new1 and cur1 != new1 and not _norm_key(row.get("parent_name2")))
        patch = {}
        for f in PARENT_FIELDS:
            if into_second and not f.endswith("2"):
                continue
            v = _norm_key(row.get(f))
            if not v:
                continue
            if v != _norm_key(s.get(f)):
                patch[f] = v
        if not patch:
            unchanged += 1
            continue
        data.update("students", s["uid"], patch, class_id, source)
        s.update(patch)
        updated += 1
    return {"total": len(rows), "updated": updated, "unchanged": unchanged,
            "unmatched": unmatched, "unmatched_count": len(unmatched)}


def parent_stats(class_id):
    """家长联系方式覆盖率统计，用于页面顶部的提示。"""
    ss = students(class_id)
    missing = [s.get("name") for s in ss
               if s.get("status", STATUS_ACTIVE) == STATUS_ACTIVE
               and not str(s.get("parent_phone") or "").strip()]
    return {"total": len(ss), "filled": len(ss) - len(missing),
            "missing": len(missing), "missing_names": missing[:20]}


def roster_stats(class_id):
    ss = students(class_id)
    active = [s for s in ss if s.get("status") == STATUS_ACTIVE]
    return {
        "total": len(ss), "active": len(active),
        "male": sum(1 for s in active if s.get("gender") == "男"),
        "female": sum(1 for s in active if s.get("gender") == "女"),
        "inactive": [{"name": s.get("name"), "status": s.get("status")}
                     for s in ss if s.get("status") != STATUS_ACTIVE],
    }


# ---------- 请假 ----------

def add_leave(class_id, payload, source="manual"):
    rec = data.insert("leaves", dict(payload), class_id, source)
    return rec


def set_dorm(class_id, student, room):
    """把学生 dorm 字段改为 room（床位关系由 dorm.json 维护）。"""
    s_ = get_student(class_id, student) if isinstance(student, str) else student
    if not s_:
        return None
    return data.update("students", s_["uid"], {"dorm": room}, class_id, "manual")


def list_leaves(class_id):
    return sorted(data.records("leaves", class_id),
                  key=lambda r: r.get("start_date", ""), reverse=True)


def leaves_on(class_id, date_str):
    out = []
    for lv in data.records("leaves", class_id):
        if lv.get("status") != "已同意":
            continue
        start = lv.get("start_date") or ""
        try:
            end = lv.get("end_date") or _add_days(start, int(lv.get("days", 1)) - 1)
        except Exception:
            end = start
        if start <= date_str <= end:
            out.append(lv)
    return out


def _add_days(dstr, n):
    try:
        d = datetime.strptime(dstr, "%Y-%m-%d") + timedelta(days=n)
        return d.strftime("%Y-%m-%d")
    except Exception:
        return dstr


# ---------- 考勤（每日快计，自动汇总请假 + 手动登记旷课/迟到） ----------

def mark_attendance(class_id, rec, source=None):
    """rec: {date, student_id, mark}，mark ∈ {旷课,迟到,早退,正常}"""
    src = source or rec.get("source") or "manual"
    existing = [r for r in data.records("attendance", class_id)
                if r.get("date") == rec.get("date") and r.get("student_id") == rec.get("student_id")]
    if existing:
        return data.update("attendance", existing[0]["uid"], {"mark": rec["mark"]}, class_id, src)
    return data.insert("attendance", rec, class_id, src)


def attendance_on(class_id, date_str):
    """返回当日应到/实到/请假/旷课/迟到明细。应到 = 在校且有当日课。"""
    ss = students(class_id)
    active_ids = {s["student_id"]: s for s in ss if s.get("status") == STATUS_ACTIVE}
    week = _week_cn(date_str)
    sched = [c for c in get_timetable(class_id) if c.get("weekday") == week]
    has_class = bool(sched)
    expected = [sid for sid in active_ids if has_class]  # MVP：有课即全员应到
    lv = {x["student_id"]: x for x in leaves_on(class_id, date_str)}
    marks = {}
    for r in data.records("attendance", class_id):
        if r.get("date") == date_str and r.get("mark") in ("旷课", "迟到", "早退", "正常"):
            marks[r.get("student_id")] = r.get("mark")
    absent, late, leave = [], [], []
    for sid in expected:
        name = active_ids[sid].get("name")
        if sid in lv:
            leave.append({"student_id": sid, "name": name,
                          "type": lv[sid].get("type", "请假")})
        elif marks.get(sid) == "旷课":
            absent.append({"student_id": sid, "name": name})
        elif marks.get(sid) in ("迟到", "早退"):
            late.append({"student_id": sid, "name": name, "mark": marks.get(sid)})
    actual = len(expected) - len(leave) - len(absent)
    return {
        "date": date_str, "has_class": has_class,
        "expected": len(expected), "actual": actual,
        "leave": leave, "absent": absent, "late": late,
    }


def _week_cn(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return "周" + "一二三四五六日"[d.weekday()]
    except Exception:
        return ""


# ---------- 待办 ----------

TODO_TYPES = ["教学", "班级管理", "行政事务"]


def add_todo(class_id, payload, source="manual"):
    rec = data.insert("todos", dict(payload), class_id, source)
    return rec


def list_todos(class_id, today=None):
    today = today or data.today_str()
    out = []
    for t in data.records("todos", class_id):
        d = dict(t)
        due = t.get("due") or ""
        if t.get("done"):
            d["bucket"] = "done"
        elif due and due < today:
            d["bucket"] = "overdue"
        elif due == today:
            d["bucket"] = "today"
        else:
            d["bucket"] = "todo"
        out.append(d)
    out.sort(key=lambda x: (x["bucket"] != "overdue", x["bucket"] != "today",
                            x.get("due") or "9999", {"高": 0, "中": 1, "低": 2}.get(x.get("priority"), 1)))
    return out


def count_todos(class_id, today=None):
    ls = list_todos(class_id, today)
    return {
        "overdue": sum(1 for t in ls if t["bucket"] == "overdue"),
        "today": sum(1 for t in ls if t["bucket"] == "today"),
        "todo": sum(1 for t in ls if t["bucket"] == "todo"),
    }


# ---------- 课表 ----------

def get_timetable(class_id):
    obj = data.get_obj("timetable", {}) or {}
    return obj.get(class_id, [])


def set_timetable(class_id, entries, source="manual"):
    obj = data.get_obj("timetable", {}) or {}
    obj[class_id] = entries
    data.set_obj("timetable", obj, source)
    return entries


WEEKDAYS = ["周一", "周二", "周三", "周四", "周五"]
PERIODS = ["1-2节", "3-4节", "5-6节", "晚自习"]


def timetable_grid(class_id, week_no=None):
    """返回 {weekday: {period: course}}；week_no 提供时按 单/双周 与 weeks 区间过滤。"""
    grid = {w: {} for w in WEEKDAYS}

    def in_weeks(spec, n):
        spec = (spec or "").strip()
        if not spec:
            return True
        for seg in spec.split(","):
            seg = seg.strip()
            if not seg:
                continue
            try:
                if "-" in seg:
                    a, b = seg.split("-")[:2]
                    if int(a) <= n <= int(b):
                        return True
                elif int(seg) == n:
                    return True
            except Exception:
                return True
        return False

    for e in get_timetable(class_id):
        if e.get("weekday") not in grid or not e.get("period"):
            continue
        if week_no is not None:
            odd = e.get("odd") or "all"
            if odd == "odd" and week_no % 2 == 0:
                continue
            if odd == "even" and week_no % 2 == 1:
                continue
            if not in_weeks(e.get("weeks"), week_no):
                continue
        val = e.get("course", "")
        if e.get("teacher"):
            val += "·" + e["teacher"]
        cur = grid[e["weekday"]].get(e["period"])
        grid[e["weekday"]][e["period"]] = (cur + " / " + val) if cur and val not in cur else (val if not cur else cur)
    return grid


def current_week_no(class_id):
    """当前是第几周（int 或 None），优先校历 class_days 自然周，其次开学日推算。"""
    from . import features
    label, src = features.week_of(class_id)
    if src == "calendar" and label.startswith("第"):
        try:
            return int(label[1:].rstrip("周"))
        except Exception:
            return None
    if src == "estimated":
        try:
            return int(label[1:].rstrip("周"))
        except Exception:
            return None
    return None


# ---------- 通知 ----------

def add_notice(class_id, payload, source="manual"):
    return data.insert("notices", dict(payload), class_id, source)


def list_notices(class_id):
    return sorted(data.records("notices", class_id),
                  key=lambda r: r.get("published_at") or r.get("created_at"), reverse=True)


# ---------- 预警（规则引擎，MVP：手动标记 + 请假联动） ----------

def add_warning(class_id, payload, source="manual"):
    return data.insert("warnings", dict(payload), class_id, source)


def list_warnings(class_id):
    return [w for w in sorted(data.records("warnings", class_id),
                              key=lambda r: r.get("created_at", ""), reverse=True)
            if not w.get("resolved")]


# ---------- 对话历史（本地保存） ----------

def chat_history(class_id):
    obj = data.get_obj("chat", {}) or {}
    return obj.get(class_id, [])


def append_chat(class_id, msg, limit=100):
    obj = data.get_obj("chat", {}) or {}
    lst = obj.setdefault(class_id, [])
    lst.append(msg)
    obj[class_id] = lst[-limit:]
    data.set_obj("chat", obj, "chat")


def clear_chat(class_id):
    obj = data.get_obj("chat", {}) or {}
    obj[class_id] = []
    data.set_obj("chat", obj, "chat")
