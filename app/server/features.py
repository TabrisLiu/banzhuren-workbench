# -*- coding: utf-8 -*-
"""二期业务：校历、学期档案、宿舍、评优、成绩与自动学业预警、班级画像。"""
import json
from datetime import datetime, timedelta

from . import data, store

# ================= 学期档案（新学期切换） =================

def get_semesters(class_id):
    obj = data.get_obj("semester_hist", {}) or {}
    cur = obj.setdefault(class_id, {"active": "", "list": []})
    cfg = data.load_config()["semester"]
    name = cfg.get("name") or ""
    if name and not any(s.get("name") == name for s in cur["list"]):
        cur["list"].append({"name": name, "start": cfg.get("start_date", ""),
                            "weeks_n": cfg.get("total_weeks", 20)})
    if name and not cur["active"]:
        cur["active"] = name
    return cur


def add_semester(class_id, sem, source="manual"):
    """登记/更新一个学期并设为当前。不删除任何旧数据。"""
    name = (sem.get("name") or "").strip()
    if not name:
        raise ValueError("学期名称必填")
    cur = get_semesters(class_id)
    entry = None
    for s in cur["list"]:
        if s.get("name") == name:
            entry = s
            break
    if entry is None:
        entry = {"name": name}
        cur["list"].append(entry)
    entry["start"] = sem.get("start", "") or entry.get("start", "")
    entry["weeks_n"] = sem.get("weeks_n") or entry.get("weeks_n") or 20
    cur["active"] = name
    obj = data.get_obj("semester_hist", {}) or {}
    obj[class_id] = cur
    data.set_obj("semester_hist", obj, source)
    cfg = data.load_config()
    cfg["semester"]["name"] = name
    if sem.get("start"):
        cfg["semester"]["start_date"] = sem["start"]
    if sem.get("weeks_n"):
        cfg["semester"]["total_weeks"] = int(sem["weeks_n"])
    data.save_config(cfg)
    return cur


def active_semester(class_id):
    cur = get_semesters(class_id)
    for s in cur["list"]:
        if s.get("name") == cur.get("active"):
            return s
    return {"name": data.load_config()["semester"].get("name") or "",
            "start": data.load_config()["semester"].get("start_date") or ""}


# ================= 校历（点选上课日） =================

def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _ds(d):
    return d.strftime("%Y-%m-%d")


def calendar_days(class_id):
    """上课日集合：weeks 范围 ∪ class_days 明细 - holidays 范围。"""
    cal = get_calendar(class_id)
    days = set()
    for w in cal.get("weeks", []):
        if w.get("start") and w.get("end"):
            try:
                a, b = _d(w["start"]), _d(w["end"])
            except Exception:
                continue
            d0 = a
            while d0 <= b:
                days.add(_ds(d0))
                d0 += timedelta(days=1)
    for s in cal.get("class_days", []):
        days.add(s)
    for h in cal.get("holidays", []):
        if h.get("start") and h.get("end"):
            try:
                a, b = _d(h["start"]), _d(h["end"])
            except Exception:
                continue
            d0 = a
            while d0 <= b:
                days.discard(_ds(d0))
                d0 += timedelta(days=1)
    return days


def set_calendar_days(class_id, class_days, source="manual"):
    """点选日历保存：直接存 class_days 明细（weeks/holidays 保留给手动模式）。"""
    obj = data.get_obj("calendar", {}) or {}
    cal = obj.setdefault(class_id, {"weeks": [], "holidays": [], "notes": ""})
    cal["class_days"] = sorted(set(class_days))
    data.set_obj("calendar", obj, source)


# ================= 宿舍管理（房间·床位） =================

def get_dorm(class_id):
    """dorm.json 结构 {class_id: {"rooms": {name:{building,beds,gender,occupants{床号:学号}}},
    "hygiene": {room: [记录]}}}；自动兼容旧格式（无 rooms 键时整个视为 hygiene）。"""
    obj = data.get_obj("dorm", {}) or {}
    d = obj.get(class_id)
    if not isinstance(d, dict):
        d = {}
    if "rooms" not in d and "hygiene" not in d:
        d = {"rooms": {}, "hygiene": d or {}}
    d.setdefault("rooms", {})
    d.setdefault("hygiene", {})
    return d


def save_dorm(class_id, d, source="manual"):
    obj = data.get_obj("dorm", {}) or {}
    obj[class_id] = d
    data.set_obj("dorm", obj, source)


def dorm_rooms(class_id):
    d = get_dorm(class_id)
    return d["rooms"]


def dorm_hygiene(class_id):
    d = get_dorm(class_id)
    return d["hygiene"]


def add_hygiene(class_id, room, date, score, note="", source="manual"):
    """记一条宿舍卫生评分。"""
    d = get_dorm(class_id)
    try:
        score = float(score)
    except Exception:
        score = 0.0
    lst = d["hygiene"].setdefault(room, [])
    lst.append({"uid": data.uuid.uuid4().hex[:10], "date": date or data.today_str(),
                "score": score, "note": note, "created_at": data.now_str()})
    lst.sort(key=lambda x: x["date"], reverse=True)
    save_dorm(class_id, d, source)
    return lst


def _room_default(name, gender_hint=""):
    building = ""
    t = name.strip()
    if t and (t[0].isalpha()):
        building = t[0].upper()
    elif "栋" in t:
        building = t.split("栋")[0][-1:]
    return {"building": building, "beds": 6, "gender": gender_hint, "occupants": {}}


def dorm_view(class_id):
    """聚合视图：花名册在籍生按宿舍号进入床位模型；未建档房间自动补建。"""
    d = get_dorm(class_id)
    rooms = d["rooms"]
    ss = [x for x in store.students(class_id) if x.get("status") == store.STATUS_ACTIVE]
    by_room = {}
    for x in ss:
        room = (x.get("dorm") or "").strip()
        if not room:
            continue
        by_room.setdefault(room, []).append(x)
    for room in by_room:
        if room not in rooms:
            g = "男" if all(x.get("gender") == "男" for x in by_room[room]) else \
                ("女" if all(x.get("gender") == "女" for x in by_room[room]) else "")
            rooms[room] = _room_default(room, g)
        r = rooms[room]
        r.setdefault("occupants", {})
        # 花名册有此人但床位无登记 → 自动安排到空床
        for x in by_room[room]:
            if x["student_id"] in set(r["occupants"].values()):
                continue
            for b in range(1, int(r.get("beds", 6)) + 1):
                if str(b) not in r["occupants"]:
                    r["occupants"][str(b)] = x["student_id"]
                    break
    out = []
    sid2s = {x["student_id"]: x for x in ss}
    for name in sorted(rooms, key=lambda k: (rooms[k].get("building", ""), k)):
        r = rooms[name]
        beds_n = int(r.get("beds", 6))
        occupants = r.get("occupants", {})
        # 剔除已不在该校/已离寝的登记
        occupants = {k: v for k, v in occupants.items() if v in sid2s}
        # 已迁走的学生床位清掉
        for k, v in list(occupants.items()):
            if (sid2s[v].get("dorm") or "").strip() != name:
                occupants.pop(k, None)
        beds = []
        for b in range(1, beds_n + 1):
            sid = occupants.get(str(b))
            stu = sid2s.get(sid)
            beds.append({"bed": b, "student_id": sid or "", "name": stu["name"] if stu else "",
                         "gender": stu.get("gender", "") if stu else ""})
        filled = sum(1 for x in beds if x["student_id"])
        genders = [x["gender"] for x in beds if x["gender"]]
        guess = "男" if genders and all(g == "男" for g in genders) else \
            ("女" if genders and all(g == "女" for g in genders) else "")
        out.append({"room": name, "building": r.get("building", ""),
                    "beds": beds_n, "capacity": beds_n, "filled": filled,
                    "gender": r.get("gender") or guess, "list": beds})
    save_dorm(class_id, d, "system")
    unassigned = [x["name"] for x in ss if not (x.get("dorm") or "").strip()]
    male = sum(1 for x in out if x["gender"] == "男")
    female = sum(1 for x in out if x["gender"] == "女")
    return {"rooms": out, "unassigned": unassigned,
            "stats": {"rooms": len(out), "male": male, "female": female,
                      "residents": sum(x["filled"] for x in out)},
            "hygiene": d["hygiene"]}


def upsert_room(class_id, name, building=None, beds=None, gender=None):
    d = get_dorm(class_id)
    r = d["rooms"].setdefault(name, _room_default(name, gender or ""))
    if building is not None:
        r["building"] = building
    if beds:
        r["beds"] = max(int(beds), len([v for v in r.get("occupants", {}).values() if v]) or int(beds))
    if gender is not None:
        r["gender"] = gender
    save_dorm(class_id, d)


def delete_room(class_id, name):
    d = get_dorm(class_id)
    d["rooms"].pop(name, None)
    save_dorm(class_id, d)


def assign_bed(class_id, room, bed, student):
    """把 student（学号或姓名）安排进 room 的 bed 号；0=腾空。返回消息。"""
    s = store.get_student(class_id, str(student))
    if not s:
        raise ValueError("学生不存在：%s" % student)
    d = get_dorm(class_id)
    if room not in d["rooms"]:
        g = s.get("gender", "")
        d["rooms"][room] = _room_default(room, g)
    r = d["rooms"][room]
    occ = r.setdefault("occupants", {})
    bed = int(bed)
    if bed < 0 or bed > int(r.get("beds", 6)):
        raise ValueError("床号超出范围（1-%s）" % r.get("beds", 6))
    # 原床占用者清掉
    for k, v in list(occ.items()):
        if v == s["student_id"] and int(k) != bed:
            occ.pop(k)
    if bed == 0:
        for k in list(occ):
            if occ[k] == s["student_id"]:
                occ.pop(k)
    else:
        prev = occ.get(str(bed))
        if prev and prev != s["student_id"]:
            # 原 occupant 挪到空床
            moved = False
            for b2 in range(1, int(r.get("beds", 6)) + 1):
                if str(b2) not in occ:
                    occ[str(b2)] = prev
                    moved = True
                    break
            if not moved:
                occ.pop(str(bed), None)
        occ[str(bed)] = s["student_id"]
    r["beds"] = max(int(r.get("beds", 6)), bed)
    save_dorm(class_id, d)
    if bed > 0:
        if s.get("dorm") != room:
            store.set_dorm(class_id, s, room)
    elif s.get("dorm") == room:
        # 腾出床位：同步清掉学生 dorm 字段，否则 dorm_view 的自动排床会把他塞回空床
        store.set_dorm(class_id, s, "")
    return "%s → %s %s号床" % (s["name"], room, ("%d" % bed) if bed else "腾出")


def import_beds(class_id, rows):
    """rows: [{room, bed, student}]，student 学号或姓名。返回 {ok, failed, count}。"""
    ok, failed = 0, []
    for x in rows:
        room = str(x.get("room", "")).strip()
        try:
            bed = int(x.get("bed", 0))
            assign_bed(class_id, room, bed, x.get("student", ""))
            ok += 1
        except Exception as e:
            failed.append("%s@%s：%s" % (x.get("student", "?"), room, str(e)[:40]))
    return {"ok": ok, "failed": failed, "count": len(rows)}


def hygiene_summary(class_id, days=14):
    """近 N 天各宿舍卫生统计。"""
    from datetime import datetime, timedelta
    d = get_dorm(class_id)
    today = datetime.now().date()
    res = {}
    for room, lst in d["hygiene"].items():
        recs = []
        for x in lst:
            try:
                dt = datetime.strptime(x.get("date", ""), "%Y-%m-%d").date()
            except Exception:
                continue
            if (today - dt).days <= days:
                recs.append(x)
        if recs:
            vals = [x.get("score", 0) for x in recs]
            res[room] = {"avg": round(sum(vals) / len(vals), 1), "n": len(recs),
                         "min": min(vals), "last": sorted(recs, key=lambda y: y["date"])[-1],
                         "records": sorted(recs, key=lambda y: y["date"], reverse=True)}
    return res


def dorm_notice(class_id, days=14):
    """生成卫生通报文本。"""
    stat = hygiene_summary(class_id, days)
    if not stat:
        return {"text": "", "error": "近 %d 天没有卫生评分记录" % days}
    perfect = [k for k, v in stat.items() if v["min"] >= 9.5]
    bad = sorted([(k, v) for k, v in stat.items() if v["avg"] < 8], key=lambda x: x[1]["avg"])
    lines = ["🏠 宿舍卫生通报（近两周 · 截至 %s）" % data.today_str(), ""]
    if perfect:
        lines.append("【通报表扬】平均分满分或全部 ≥9.5 的宿舍：" + "、".join(perfect) + "，继续保持！")
    if stat:
        ranked = sorted(stat.items(), key=lambda kv: -kv[1]["avg"])
        lines.append("【各宿舍均分】" + "、".join("%s %.1f" % (k, v["avg"]) for k, v in ranked[:12]))
    if bad:
        lines.append("")
        lines.append("【重点关注】以下宿舍两周均分低于 8，请室长今日内提交整改计划：")
        for k, v in bad:
            low = [x for x in v["records"] if x.get("score", 10) < 8]
            det = "；".join("%s %s 分%s" % (x["date"][5:], x["score"], ("（" + x["note"] + "）") if x.get("note") else "")
                            for x in low[:4])
            lines.append("· %s：均分 %.1f，扣分明细：%s" % (k, v["avg"], det))
    if not bad:
        lines.append("本周期无低分宿舍，整体表现良好 👍")
    text = "\n".join(lines)
    store.add_notice(class_id, {"title": "宿舍卫生通报（近两周）", "content": text,
                                "audience": "全体家长", "status": "草稿"}, "system")
    return {"text": text, "perfect": perfect, "bad": [k for k, _ in bad]}


# ================= 评优评奖 =================

def _honor_grade(name):
    n = name or ""
    if any(k in n for k in ("一", "1")):
        return 3
    if any(k in n for k in ("二", "2")):
        return 2
    if any(k in n for k in ("三", "3")):
        return 1
    return 1


def award_stats(class_id, sem=None):
    """按当前学期考试综合排名 + 奖惩记录，给出奖学金预分名单。"""
    sem = sem or active_semester(class_id).get("name") or ""
    sem_start = sem and sem or ""
    ss = {s["student_id"]: s for s in store.students(class_id)
          if s.get("status") == store.STATUS_ACTIVE}
    # 综合分：各考试平均得分率（不区分学期，数据量小；显示所用考试数）
    per = {}
    for g in data.records("grades", class_id):
        full = g.get("full") or 100
        for it in g.get("items", []):
            d = per.setdefault(it.get("student_id"), {"sid": it.get("student_id"),
                    "name": it.get("name"), "ratios": [], "exams": set()})
            d["ratios"].append(100.0 * it.get("score", 0) / max(full, 1))
            d["exams"].add(g.get("exam"))
    rows = []
    for sid, d in per.items():
        rows.append({"student_id": sid, "name": d["name"],
                     "score": round(sum(d["ratios"]) / len(d["ratios"]), 1),
                     "exams": len(d["exams"]), "award": "", "note": ""})
    rows.sort(key=lambda x: -x["score"])
    n = len(rows)
    for i, r in enumerate(rows):
        if n and i < max(1, round(n * 0.10)):
            r["award"] = "一等奖学金"
        elif i < max(1, round(n * 0.25)):
            r["award"] = "二等奖学金"
        elif i < max(1, round(n * 0.45)):
            r["award"] = "三等奖学金"
    awards = data.records("awards", class_id)
    honors = {}
    for a in awards:
        nm = a.get("student", "")
        if (a.get("type") or "奖励") == "奖励":
            honors.setdefault(nm, []).append(a)
    # 奖惩记录并入建议：一等需无处分
    punished = {a.get("student") for a in awards if (a.get("type") or "") == "处分"}
    for r in rows:
        r["honor_n"] = len(honors.get(r["name"], []))
        if r["award"] and r["name"] in punished:
            r["note"] = "有处分记录，建议降档/公示核实"
    for nm, lst in honors.items():
        if not any(r["name"] == nm for r in rows):
            rows.append({"student_id": "", "name": nm, "score": None, "exams": 0,
                         "award": "", "note": "无成绩数据", "honor_n": len(lst)})
    recent_exams = len({g.get("exam") for g in data.records("grades", class_id)})
    return {"semester": sem, "rows": rows, "honors": honors, "punished": list(punished),
            "recent_exams": recent_exams}


# ================= 课表导入解析 =================

def parse_timetable_text(text):
    """通用课表解析（文本行）。支持两种格式：
    A: 周X,节次,课程  或  周三\t第1-2节\t高数
    B: 周X,第N周/单双周,节次,课程
    返回 entries + 未识别行。"""
    wk_pat = ("周一", "周二", "周三", "周四", "周五", "周六", "周日",
              "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
    entries, skipped = [], []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.replace("\t", ",").replace("，", ",").split(",") if p.strip()]
        norm = {"一": "周一", "二": "周二", "三": "周三", "四": "周四",
                "五": "周五", "六": "周六", "日": "周日"}
        raw_wk = ""
        for p in parts:
            if p in wk_pat:
                raw_wk = norm.get(p[-1], "")
                break
        if not raw_wk:
            skipped.append(line)
            continue
        rest = [p for p in parts if p not in wk_pat]
        course = ""; period = ""; odd = "all"; weeks = ""
        import re as _re
        clean = []
        for p in rest:
            if p in ("单周", "单"):
                odd = "odd"; continue
            if p in ("双周", "双"):
                odd = "even"; continue
            m = _re.search(r"(\d+)\s*[-~至]\s*(\d+)\s*周(次)?", p)
            if m:
                weeks = "%s-%s" % (m.group(1), m.group(2))
                p = _re.sub(r"[\s,，]*\d+\s*[-~至]\s*\d+\s*周(次)?", "", p).strip()
            if "单周" in p or p.endswith(" 单"):
                odd = "odd"
            if "双周" in p or p.endswith(" 双"):
                odd = "even"
            p = p.replace("单周", "").replace("双周", "").strip()
            if p:
                clean.append(p)
        if len(clean) >= 2:
            course = clean[-1]
            period = clean[-2]
        elif len(clean) == 1:
            course = clean[0]
            period = "1-2节"
        period = _re.sub(r"^第", "", period).strip()
        entries.append({"weekday": raw_wk, "period": period, "course": course,
                        "odd": odd, "weeks": weeks})
    return entries, skipped


# ================= 校历 =================

DEFAULT_CAL = {"weeks": [], "holidays": [], "notes": ""}


def get_calendar(class_id):
    obj = data.get_obj("calendar", {}) or {}
    cal = (obj.get(class_id) or {}).copy()
    for k, v in DEFAULT_CAL.items():
        cal.setdefault(k, json.loads(json.dumps(v)))
    return cal


def set_calendar(class_id, cal, source="manual"):
    obj = data.get_obj("calendar", {}) or {}
    obj[class_id] = cal
    data.set_obj("calendar", obj, source)


def week_of(class_id, date_str=None):
    """返回 (周次描述, 来源)。校历（weeks/class_days）优先，无校历按开学日期推算。"""
    date_str = date_str or data.today_str()
    cal = get_calendar(class_id)
    days = calendar_days(class_id)
    if days:
        if date_str in days:
            try:
                d0 = _d(date_str)
                monday = d0 - timedelta(days=d0.weekday())
                keys = sorted({_d(s) - timedelta(days=_d(s).weekday()) for s in days})
                if monday in keys:
                    base = None
                    sd = data.load_config()["semester"].get("start_date")
                    if sd:
                        try:
                            base = _d(sd) - timedelta(days=_d(sd).weekday())
                        except Exception:
                            base = None
                    if base:
                        idx = max(1, (monday - base).days // 7 + 1)
                    else:
                        idx = keys.index(monday) + 1
                    return ("第%d周" % idx, "calendar")
            except Exception:
                pass
        for h in cal.get("holidays", []):
            if h.get("start") and h.get("end") and h["start"] <= date_str <= h["end"]:
                return (h.get("name", "假期"), "calendar")
        return ("非教学周", "calendar")
    for w in cal.get("weeks", []):
        if w.get("start") and w.get("end") and w["start"] <= date_str <= w["end"]:
            return ("第%s周" % w.get("week", "?"), "calendar")
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        for h in cal.get("holidays", []):
            if h.get("start") and h.get("end") and h["start"] <= date_str <= h["end"]:
                return (h.get("name", "假期"), "calendar")
    except Exception:
        pass
    # fallback：按开学日期推算
    cfg = data.load_config()
    sd = cfg["semester"].get("start_date")
    if sd:
        try:
            w = (datetime.strptime(date_str, "%Y-%m-%d") - datetime.strptime(sd, "%Y-%m-%d")).days // 7 + 1
            if w >= 1:
                return ("第%d周" % w, "estimated")
        except Exception:
            pass
    return ("", "none")


# ================= 成绩 =================

def save_grade_sheet(class_id, sheet, source="manual"):
    """sheet: {exam, subject, date, items:[{student_id, name, score}]}。
    同 考试+科目 已有记录则整体更新。返回 (rec, created)。"""
    exam = (sheet.get("exam") or "").strip()
    subject = (sheet.get("subject") or "").strip()
    if not exam or not subject:
        raise ValueError("考试名称与科目必填")
    items = []
    for it in sheet.get("items", []):
        try:
            score = round(float(it.get("score")), 1)
        except (TypeError, ValueError):
            continue
        items.append({"student_id": it.get("student_id", ""),
                      "name": it.get("name", ""), "score": score})
    existing = [g for g in data.records("grades", class_id)
                if g.get("exam") == exam and g.get("subject") == subject]
    payload = {"exam": exam, "subject": subject,
               "date": sheet.get("date") or data.today_str(),
               "full": sheet.get("full") or 100, "items": items}
    if existing:
        rec = data.update("grades", existing[0]["uid"], payload, class_id, source)
        return rec, False
    rec = data.insert("grades", payload, class_id, source)
    return rec, True


def grade_analysis(class_id, exam=None, subject=None):
    """按 exam(+subject) 聚合分析；不传则取最新一次考试全部科目汇总。"""
    gs = data.records("grades", class_id)
    if exam:
        gs = [g for g in gs if g.get("exam") == exam]
    if subject:
        gs = [g for g in gs if g.get("subject") == subject]
    if not gs:
        return None
    latest = max(g.get("date", "") for g in gs)
    gs = [g for g in gs if g.get("date") == latest]
    scores = []          # (student_id, name, subject, score)
    per_subject = {}
    for g in gs:
        for it in g.get("items", []):
            scores.append((it.get("student_id", ""), it.get("name", ""),
                           g.get("subject", ""), it.get("score", 0)))
            per_subject.setdefault(g.get("subject", ""), []).append(it.get("score", 0))
    if not scores:
        return None
    vals = [s[3] for s in scores]
    n = len(vals)
    def pct(pred):
        return round(100.0 * sum(1 for v in vals if pred(v)) / n, 1) if n else 0
    by_stu = {}
    for sid, name, subj, sc in scores:
        d = by_stu.setdefault(sid, {"name": name, "subjects": {}})
        d["subjects"][subj] = sc
    dist = {"<60": 0, "60-70": 0, "70-85": 0, ">=85": 0}
    for v in vals:
        k = "<60" if v < 60 else "60-70" if v < 70 else "70-85" if v < 85 else ">=85"
        dist[k] += 1
    return {
        "exam": exam or gs[0].get("exam"), "date": latest,
        "count": n, "avg": round(sum(vals) / n, 1),
        "max": max(vals), "min": min(vals),
        "pass_rate": pct(lambda v: v >= 60), "good_rate": pct(lambda v: v >= 85),
        "dist": dist, "per_subject": {k: round(sum(v) / len(v), 1)
                                      for k, v in per_subject.items() if v},
        "failed": sorted([{"student_id": sid, "name": name, "subject": subj,
                           "score": sc} for sid, name, subj, sc in scores if sc < 60],
                         key=lambda x: x["score"]),
    }


# ================= 学业分析（综合概览/明细/学科/排名/进退步/趋势） =================

def exam_list(class_id):
    out = {}
    for g in data.records("grades", class_id):
        e = out.setdefault(g.get("exam"), {"exam": g.get("exam"), "date": "", "subjects": []})
        e["date"] = max(e["date"], g.get("date", ""))
        e["subjects"].append(g.get("subject"))
    return sorted(out.values(), key=lambda x: x["date"], reverse=True)


def _students_totals(class_id, exam):
    """某考试 → ({sid: {name, subj:{s:(score,full)}, total, full_total, ratio}}, [subject rows])"""
    per = {}
    subj_rows = []
    for g in data.records("grades", class_id):
        if g.get("exam") != exam:
            continue
        full = g.get("full") or 100
        subj_rows.append({"subject": g.get("subject"), "full": full,
                          "scores": {it.get("student_id"): it.get("score") for it in g.get("items", [])},
                          "names": {it.get("student_id"): it.get("name") for it in g.get("items", [])}})
        for it in g.get("items", []):
            d = per.setdefault(it.get("student_id"), {"student_id": it.get("student_id"),
                                                      "name": it.get("name"), "subj": {},
                                                      "total": 0.0, "full_total": 0})
            d["subj"][g.get("subject")] = (it.get("score", 0), full)
            d["total"] += it.get("score", 0)
            d["full_total"] += full
    for d in per.values():
        d["total"] = round(d["total"], 1)
        d["ratio"] = round(100.0 * d["total"] / d["full_total"], 1) if d["full_total"] else 0
    return per, subj_rows


def grade_report(class_id, exam):
    """学业分析主数据：一次考试的全套统计。"""
    per, subj_rows = _students_totals(class_id, exam)
    if not subj_rows:
        return None
    n = len(per)
    totals = [d["total"] for d in per.values()]
    ratios = [d["ratio"] for d in per.values()]
    ranked = sorted(per.values(), key=lambda d: -d["total"])
    for i, d in enumerate(ranked):
        d["rank"] = i + 1
    def subj_stat(sr):
        vals = [v for v in sr["scores"].values() if v is not None]
        m = max(sr["full"], 1)
        return {"subject": sr["subject"], "full": sr["full"], "count": len(vals),
                "avg": round(sum(vals) / len(vals), 1) if vals else 0,
                "max": max(vals) if vals else 0, "min": min(vals) if vals else 0,
                "pass_rate": round(100.0 * sum(1 for v in vals if v >= 0.6 * m) / len(vals), 1) if vals else 0,
                "excellent": round(100.0 * sum(1 for v in vals if v >= 0.85 * m) / len(vals), 1) if vals else 0,
                "failed": sorted([{"student_id": s, "name": sr["names"].get(s, ""), "score": v}
                                  for s, v in sr["scores"].items() if v is not None and v < 0.6 * m],
                                 key=lambda x: x["score"])}
    subjects = [subj_stat(sr) for sr in subj_rows]
    tiers = {"A(≥90%)": sum(1 for r in ratios if r >= 90),
             "B(80-90)": sum(1 for r in ratios if 80 <= r < 90),
             "C(70-80)": sum(1 for r in ratios if 70 <= r < 80),
             "D(60-70)": sum(1 for r in ratios if 60 <= r < 70),
             "E(<60)": sum(1 for r in ratios if r < 60)}
    focus = sorted(subjects, key=lambda x: x["avg"] / max(x["full"], 1))[:3]
    report = {
        "exam": exam,
        "date": max(sr for sr in [g.get("date", "") for g in data.records("grades", class_id)
                                  if g.get("exam") == exam] or [""]),
        "kpi": {"count": n, "subjects": len(subjects),
                "avg_total": round(sum(totals) / n, 1) if n else 0,
                "full_total": max((d["full_total"] for d in per.values()), default=0),
                "max_total": max(totals) if totals else 0, "min_total": min(totals) if totals else 0,
                "range": (max(totals) - min(totals)) if totals else 0,
                "avg_ratio": round(sum(ratios) / n, 1) if n else 0,
                "tiers": tiers, "tier_good": tiers["A(≥90%)"] + tiers["B(80-90)"]},
        "subjects": subjects,
        "focus": [{"subject": f["subject"], "avg": f["avg"], "full": f["full"],
                   "pass_rate": f["pass_rate"], "failed_n": len(f["failed"])} for f in focus],
        "top": [{"rank": d["rank"], "name": d["name"], "total": d["total"], "ratio": d["ratio"]}
                for d in ranked[:10]],
        "ranking": [{"rank": d["rank"], "student_id": d["student_id"], "name": d["name"],
                     "total": d["total"], "ratio": d["ratio"]} for d in ranked],
        "detail": [{"student_id": d["student_id"], "name": d["name"],
                    "scores": {s: v[0] for s, v in d["subj"].items()},
                    "total": d["total"], "rank": d["rank"]} for d in ranked],
        "failed_students": sorted(
            [{"name": x.get("name", ""), "subject": sub["subject"], "score": x["score"]}
             for sub in subjects for x in sub["failed"]],
            key=lambda x: (x["name"], x["subject"])),
    }
    # ---- 进退步：与上一场考试的总分对比 ----
    exams = exam_list(class_id)
    prev_exam = None
    for i, e in enumerate(exams):
        if e["exam"] == exam and i + 1 < len(exams):
            prev_exam = exams[i + 1]["exam"]
            break
    report["prev_exam"] = prev_exam
    if prev_exam:
        prev_per, _ = _students_totals(class_id, prev_exam)
        moves = []
        for sid, d in per.items():
            p = prev_per.get(sid)
            if p and d["subj"].keys() & p["subj"].keys():
                delta = round(d["total"] - p["total"], 1)
                moves.append({"student_id": sid, "name": d["name"], "prev": p["total"],
                              "curr": d["total"], "delta": delta, "rank": d["rank"]})
        moves.sort(key=lambda x: -x["delta"])
        report["up"] = [m for m in moves if m["delta"] > 0][:8]
        report["down"] = [m for m in reversed(moves) if m["delta"] < 0][:8]
    else:
        report["up"], report["down"] = [], []
    # ---- 历次趋势：所有考试按时间 ----
    trend = []
    for e in sorted(exams, key=lambda x: x["date"]):
        p2, _ = _students_totals(class_id, e["exam"])
        rs = [d["ratio"] for d in p2.values()]
        trend.append({"exam": e["exam"], "date": e["date"], "count": len(p2),
                      "avg_ratio": round(sum(rs) / len(rs), 1) if rs else 0})
    report["trend"] = trend
    return report


def run_grade_rules(class_id, source="auto"):
    """自动学业预警：挂科>=N 门（红灯）；同科连续下滑>=M 分（黄灯）。返回生成/更新的预警列表。"""
    cfg = data.load_config()
    fail_n = int(cfg["settings"].get("warn_fail_courses", 2))
    drop_n = int(cfg["settings"].get("warn_score_drop", 10))
    gs = data.records("grades", class_id)
    per_stu = {}      # sid -> {name, subj: [(date, score)]}
    for g in gs:
        for it in g.get("items", []):
            d = per_stu.setdefault(it.get("student_id", ""),
                                   {"name": it.get("name", ""), "subj": {}})
            d["subj"].setdefault(g.get("subject", ""), []).append(
                (g.get("date", ""), it.get("score", 0)))
    raised = []
    existing = {(w.get("student"), w.get("kind")): w
                for w in data.records("warnings", class_id) if not w.get("resolved")}
    for sid, info in per_stu.items():
        # 取各科目最近一次成绩判断挂科，而非历史最低分
        failed = [s for s, lst in info["subj"].items() if lst and sorted(lst)[-1][1] < 60]
        if len(failed) >= fail_n:
            key = (info["name"], "学业")
            desc = "挂科 %d 门（%s）" % (len(failed), "、".join(sorted(failed)[:4]))
            w = existing.get(key)
            if w:
                data.update("warnings", w["uid"], {"level": "红", "desc": desc}, class_id, source)
            else:
                store.add_warning(class_id, {"student": info["name"], "kind": "学业",
                                             "level": "红", "desc": desc,
                                             "resolved": False, "auto": True})
            raised.append("%s：%s" % (info["name"], desc))
        for subj, lst in info["subj"].items():
            lst = sorted(lst)
            if len(lst) >= 2 and lst[-1][1] <= lst[-2][1] - drop_n:
                key = (info["name"], "学业")
                desc = "%s 成绩连续下滑（%s→%s 分）" % (subj, lst[-2][1], lst[-1][1])
                w = existing.get(key)
                if w and "下滑" not in (w.get("desc") or ""):
                    continue  # 已有红灯时不再叠加黄灯
                if w:
                    data.update("warnings", w["uid"],
                                {"level": "黄", "desc": desc}, class_id, source)
                else:
                    store.add_warning(class_id, {"student": info["name"], "kind": "学业",
                                                 "level": "黄", "desc": desc,
                                                 "resolved": False, "auto": True})
                raised.append("%s：%s" % (info["name"], desc))
                break
    return raised


# ================= 班级画像（数据统计页） =================

def class_portrait(class_id):
    ss = store.students(class_id)
    active = [s for s in ss if s.get("status") == store.STATUS_ACTIVE]
    tags = store.get_tags(class_id)
    tag_counts = {}
    for lst in tags.values():
        for t in lst:
            tag_counts[store.TAG_LABELS.get(t, t)] = tag_counts.get(store.TAG_LABELS.get(t, t), 0) + 1
    origin = {}
    for s in active:
        o = (s.get("origin") or "未知").strip()[:2] + ("…省" if len(s.get("origin") or "") > 2 else "")
        origin[o] = origin.get(o, 0) + 1
    warns = store.list_warnings(class_id)
    warn_by_kind = {}
    for w in warns:
        warn_by_kind[w.get("kind", "其他")] = warn_by_kind.get(w.get("kind", "其他"), 0) + 1
    # 近30天考勤汇总
    today = datetime.now()
    leave_cnt = absent_cnt = 0
    days = 0
    for i in range(30):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        a = store.attendance_on(class_id, d)
        if a.get("has_class"):
            days += 1
            leave_cnt += len(a.get("leave", []))
            absent_cnt += len(a.get("absent", []))
    return {
        "total": len(ss), "active": len(active),
        "male": sum(1 for s in active if s.get("gender") == "男"),
        "female": sum(1 for s in active if s.get("gender") == "女"),
        "origin": sorted(origin.items(), key=lambda x: -x[1]),
        "tag_counts": sorted(tag_counts.items(), key=lambda x: -x[1]),
        "warnings_total": len(warns), "warnings_by_kind": warn_by_kind,
        "attend_days": days, "leave_cnt": leave_cnt, "absent_cnt": absent_cnt,
        "inactive": [{"name": s.get("name"), "status": s.get("status")}
                     for s in ss if s.get("status") != store.STATUS_ACTIVE],
    }
