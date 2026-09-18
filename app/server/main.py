# -*- coding: utf-8 -*-
"""班主任工作台 · 本地服务（FastAPI）。仅监听 127.0.0.1，数据不出本机。
启动：python3 -m app.server.main  （见 README/一键启动脚本）
"""
import json
import os
import sys
import threading
import time
import uuid
import webbrowser

import httpx
import uvicorn
from fastapi import Body, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import ai, data, features, office, store

def _resolve_web_dir():
    """前端静态资源目录。
    - 打包后：前端随包打进临时解压目录 sys._MEIPASS，只读、随程序释放即可。
    - 开发环境：项目内的 app/web。
    """
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "app", "web")
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web"))


WEB_DIR = _resolve_web_dir()
PORT = int(os.environ.get("BZK_PORT", "8790"))


def _class_id():
    return data.load_config()["class"].get("class_id") or "default"


def create_app():
    from fastapi import FastAPI
    global app
    data.refresh_storage()
    application = FastAPI(title="班主任工作台", docs_url=None, redoc_url=None)

    @application.middleware("http")
    async def no_cache_for_app(request, call_next):
        response = await call_next(request)
        p = request.url.path
        if p == "/" or p.endswith((".html", ".js", ".css")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    # ---------- 配置 / 首用向导 ----------
    def _config_for_client(cfg):
        cfg = json.loads(json.dumps(cfg))
        if cfg["ai"].get("api_key"):
            cfg["ai"]["api_key"] = "****" + cfg["ai"]["api_key"][-6:]
            cfg["ai"]["has_key"] = True
        else:
            cfg["ai"]["has_key"] = False
        return cfg

    @application.get("/api/config")
    def get_config():
        return _config_for_client(data.load_config())

    @application.post("/api/config")
    def post_config(body: dict = Body(...)):
        cfg = data.load_config()
        if "wizard_done" in body:
            cfg["initialized"] = bool(body["wizard_done"])
        c = body.get("class") or {}
        for k in ("name", "major", "grade", "head_teacher", "phone"):
            if c.get(k):
                cfg["class"][k] = c[k]
        if isinstance(c.get("size_expect"), int) and c["size_expect"] > 0:
            cfg["class"]["size_expect"] = c["size_expect"]
        s = body.get("semester") or {}
        for k in ("name", "start_date"):
            if s.get(k):
                cfg["semester"][k] = s[k]
        if s.get("total_weeks"):
            try:
                cfg["semester"]["total_weeks"] = int(s["total_weeks"])
            except Exception:
                pass
        a = body.get("ai") or {}
        for k in ("provider", "base_url", "model", "vision_model"):
            if a.get(k):
                cfg["ai"][k] = a[k]
        if a.get("api_key") and not a["api_key"].startswith("****"):
            cfg["ai"]["api_key"] = a["api_key"].strip()
        # DeepSeek 内置默认：base_url/model 固定，无需用户输入
        if cfg["ai"].get("provider") == "deepseek":
            cfg["ai"]["base_url"] = "https://api.deepseek.com"
            cfg["ai"]["model"] = "deepseek-flash"
        cfg["ai"].pop("vision_model", None)
        stg = body.get("storage") or {}
        if "data_dir" in stg:
            cfg.setdefault("storage", {})["data_dir"] = stg["data_dir"] or ""
        st = body.get("settings") or {}
        for k in ("warn_fail_courses", "warn_score_drop"):
            if k in st:
                try:
                    cfg["settings"][k] = int(st[k])
                except Exception:
                    pass
        for k in ("leave_notify_parent", "privacy_warn"):
            if k in st:
                cfg["settings"][k] = bool(st[k])
        data.save_config(cfg)
        return _config_for_client(cfg)

    # ---------- 学生 ----------
    @application.get("/api/students")
    def api_students(q: str = "", tag: str = "", status: str = ""):
        cid = _class_id()
        ss = store.students(cid)
        tags = store.get_tags(cid)
        if tag:
            ss = [s for s in ss if tag in tags.get(s["student_id"], [])]
        if status:
            ss = [s for s in ss if s.get("status") == status]
        if q:
            ql = q.lower()
            def hit(s):
                hay = " ".join([s.get("student_id", ""), s.get("name", ""),
                                s.get("dorm", ""), s.get("parent_name", "")]).lower()
                return ql in hay
            ss = [s for s in ss if hit(s)]
        for s in ss:
            s["tags"] = tags.get(s["student_id"], [])
        ss.sort(key=lambda s: s.get("student_id", ""))
        return {"students": ss, "stats": store.roster_stats(cid),
                "tag_counts": {store.TAG_LABELS[k]: sum(1 for lst in tags.values() if k in lst)
                               for k in store.TAG_LABELS}}

    @application.get("/api/students/{sid}")
    def api_student_detail(sid: str):
        cid = _class_id()
        s = store.get_student(cid, sid)
        if not s:
            return JSONResponse({"error": "学生不存在"}, status_code=404)
        s = dict(s)
        s["tags"] = store.get_tags(cid).get(s["student_id"], [])
        s["timeline"] = []
        for lv in store.list_leaves(cid):
            if lv.get("student") == s["name"]:
                s["timeline"].append({"ts": lv.get("start_date"), "kind": "请假",
                                      "text": "%s %s～%s %s" % (
                                          lv.get("type"), lv.get("start_date"),
                                          lv.get("end_date", ""), lv.get("reason", ""))})
        for w in data.records("warnings", cid):
            if w.get("student") == s["name"]:
                s["timeline"].append({"ts": w.get("created_at"), "kind": "预警",
                                      "text": "[%s·%s] %s" % (w.get("level"), w.get("kind"),
                                                              w.get("desc", ""))})
        for at in data.records("attendance", cid):
            if at.get("student_id") == s["student_id"] and at.get("mark") in ("旷课", "迟到", "早退"):
                s["timeline"].append({"ts": at.get("date"), "kind": "考勤",
                                      "text": at.get("mark") + (" " + at.get("reason", "") if at.get("reason") else "")})
        s["timeline"].sort(key=lambda x: x.get("ts") or "", reverse=True)
        return s

    @application.post("/api/students")
    def api_student_save(body: dict = Body(...)):
        cid = _class_id()
        s, created = store.upsert_student(cid, body, "manual")
        if not s:
            return JSONResponse({"error": "需要学号"}, status_code=400)
        return {"student": s, "created": created}

    @application.post("/api/students/{sid}/tags")
    def api_student_tag(sid: str, body: dict = Body(...)):
        cid = _class_id()
        s = store.get_student(cid, sid)
        if not s:
            return JSONResponse({"error": "学生不存在"}, status_code=404)
        store.set_tag(cid, s["student_id"], body.get("tag", ""), bool(body.get("on", True)))
        return {"ok": True, "tags": store.get_tags(cid).get(s["student_id"], [])}

    @application.post("/api/students/{sid}/delete")
    def api_student_delete(sid: str):
        cid = _class_id()
        s = store.get_student(cid, sid)
        if not s:
            return JSONResponse({"error": "学生不存在"}, status_code=404)
        return {"ok": store.remove("students", s["uid"], cid, "manual")}

    # ---------- Excel ----------
    @application.post("/api/roster/import")
    async def api_roster_import(file: UploadFile = File(...), apply: str = Form("1")):
        cid = _class_id()
        safe_name = os.path.basename((file.filename or "roster.xlsx").replace("\\", "/"))
        tmp = os.path.join(data.EXCEL_DIR, "incoming_" + safe_name)
        content = await file.read()
        with open(tmp, "wb") as f:
            f.write(content)
        rows, meta = office.parse_roster_xlsx(tmp)
        os.remove(tmp)
        if not rows:
            first = meta.get("first_row") or meta.get("headers") or []
            meta["error"] = ("未识别到表头：文件首行需包含「学号、姓名」等列名（当前识别到：%s）。"
                             "请检查是否选错文件/工作表，或把首行改为标准列名后再导入。"
                             % ("、".join(first[:8]) if first else "空行"))
        result = {"meta": meta, "count": len(rows), "preview": rows[:8]}
        if apply == "1" and rows:
            result["applied"] = store.import_roster(cid, rows)
        return result

    # ---------- 家长名单 ----------
    @application.get("/api/parents")
    def api_parents(q: str = "", only_missing: str = ""):
        cid = _class_id()
        ss = store.students(cid)
        ledger = data.records("family", cid)
        last, cnt = {}, {}
        for r in ledger:
            nm = (r.get("student") or "").strip()
            if not nm:
                continue
            d = r.get("date") or (r.get("created_at") or "")[:10]
            if d and d > last.get(nm, ""):
                last[nm] = d
            cnt[nm] = cnt.get(nm, 0) + 1
        if q:
            ql = q.lower()
            ss = [s for s in ss if ql in " ".join([
                s.get("student_id", ""), s.get("name", ""), s.get("parent_name", ""),
                s.get("parent_phone", ""), s.get("parent_name2", ""),
                s.get("parent_phone2", "")]).lower()]
        if only_missing == "1":
            ss = [s for s in ss if not str(s.get("parent_phone") or "").strip()]
        ss = sorted(ss, key=lambda s: s.get("student_id", ""))
        return {"parents": [{
            "student_id": s.get("student_id", ""), "name": s.get("name", ""),
            "gender": s.get("gender", ""), "dorm": s.get("dorm", ""),
            "status": s.get("status", ""),
            "parent_name": s.get("parent_name", ""), "parent_relation": s.get("parent_relation", ""),
            "parent_phone": s.get("parent_phone", ""),
            "parent_name2": s.get("parent_name2", ""), "parent_relation2": s.get("parent_relation2", ""),
            "parent_phone2": s.get("parent_phone2", ""),
            "last_contact": last.get(s.get("name", ""), ""),
            "contact_count": cnt.get(s.get("name", ""), 0),
        } for s in ss], "stats": store.parent_stats(cid)}

    @application.post("/api/parents/import")
    async def api_parents_import(file: UploadFile = File(...), apply: str = Form("1")):
        cid = _class_id()
        safe_name = os.path.basename((file.filename or "parents.xlsx").replace("\\", "/"))
        tmp = os.path.join(data.EXCEL_DIR, "incoming_parents_" + safe_name)
        content = await file.read()
        with open(tmp, "wb") as f:
            f.write(content)
        rows, meta = office.parse_parent_xlsx(tmp)
        if not rows:
            first = meta.get("first_row") or meta.get("headers") or []
            meta["error"] = ("未识别到家长名单表头：需要「学号」或「学生姓名」中的至少一列，"
                             "加上「家长姓名」或「联系电话」（当前识别到：%s）。"
                             % ("、".join(first[:8]) if first else "空行"))
        result = {"meta": meta, "count": len(rows), "preview": rows[:8]}
        if apply == "1" and rows:
            result["applied"] = store.import_parents(cid, rows)
        return result

    @application.post("/api/parents/export")
    def api_parents_export():
        cid = _class_id()
        p = os.path.join(data.EXCEL_DIR, "家长名单_%s.xlsx" % time.strftime("%Y%m%d_%H%M%S"))
        office.export_parents_xlsx(cid, p, data.records("family", cid))
        return FileResponse(p, filename=os.path.basename(p))

    @application.post("/api/parents/template")
    def api_parents_template():
        cid = _class_id()
        p = os.path.join(data.EXCEL_DIR, "家长名单导入模板_%s.xlsx" % time.strftime("%Y%m%d_%H%M%S"))
        office.export_parents_template(cid, p)
        return FileResponse(p, filename=os.path.basename(p))

    @application.post("/api/roster/export")
    def api_roster_export():
        cid = _class_id()
        p = os.path.join(data.EXCEL_DIR, "花名册_%s.xlsx" % time.strftime("%Y%m%d_%H%M%S"))
        office.export_roster_xlsx(cid, p)
        return FileResponse(p, filename=os.path.basename(p))

    @application.post("/api/todos/export")
    def api_todos_export():
        cid = _class_id()
        p = os.path.join(data.EXCEL_DIR, "待办_%s.xlsx" % time.strftime("%Y%m%d_%H%M%S"))
        office.export_todos_xlsx(cid, p)
        return FileResponse(p, filename=os.path.basename(p))

    @application.post("/api/attendance/export")
    def api_attendance_export(date: str = ""):
        cid = _class_id()
        d = date or data.today_str()
        p = os.path.join(data.EXCEL_DIR, "考勤_%s.xlsx" % d)
        office.export_attendance_xlsx(cid, p, d)
        return FileResponse(p, filename=os.path.basename(p))

    # ---------- Word ----------
    @application.post("/api/report/student/{sid}")
    def api_report_student(sid: str):
        cid = _class_id()
        s = store.get_student(cid, sid)
        if not s:
            return JSONResponse({"error": "学生不存在"}, status_code=404)
        p = os.path.join(data.WORD_DIR,
                         "成长档案_%s_%s.docx" % (s.get("name", sid), time.strftime("%Y%m%d_%H%M%S")))
        office.export_student_word(cid, sid, p)
        return FileResponse(p, filename=os.path.basename(p))

    @application.post("/api/report/summary")
    def api_report_summary():
        cid = _class_id()
        p = os.path.join(data.WORD_DIR, "班级汇总_%s.docx" % time.strftime("%Y%m%d_%H%M%S"))
        office.export_summary_word(cid, p)
        return FileResponse(p, filename=os.path.basename(p))

    # ---------- 首页 ----------
    @application.get("/api/home")
    def api_home():
        cid = _class_id()
        cfg = data.load_config()
        today = data.today_str()
        wk_label, wk_src = features.week_of(cid, today)
        cal = features.get_calendar(cid)
        wk_row = None
        for w in cal.get("weeks", []):
            if w.get("start") and w.get("end") and w["start"] <= today <= w["end"]:
                wk_row = w
                break
        next_hol = None
        for h in sorted(cal.get("holidays", []), key=lambda x: x.get("start", "")):
            if h.get("start") and h.get("end") and h["end"] >= today:
                next_hol = h
                break
        week_no = store.current_week_no(cid)
        return {
            "today": today,
            "class_name": cfg["class"].get("name", ""),
            "semester": features.active_semester(cid).get("name", ""),
            "week_label": wk_label,
            "week_source": wk_src,
            "week_no": week_no,
            "week_row": wk_row,
            "next_holiday": next_hol,
            "calendar_loaded": bool(cal.get("weeks") or cal.get("class_days")),
            "todos": store.list_todos(cid, today)[:20],
            "todo_counts": store.count_todos(cid, today),
            "warnings": store.list_warnings(cid),
            "timetable": store.timetable_grid(cid, week_no),
            "weekday": store._week_cn(today),
            "attendance": store.attendance_on(cid, today),
            "leaves_today": store.leaves_on(cid, today),
            "notices": store.list_notices(cid)[:5],
        }

    # ---------- 待办 ----------
    @application.post("/api/todos")
    def api_todo_add(body: dict = Body(...)):
        cid = _class_id()
        t = store.add_todo(cid, {
            "title": body.get("title", "").strip(),
            "due": body.get("due", ""), "time": body.get("time", ""),
            "category": body.get("category") or "班级管理",
            "priority": body.get("priority") or "中", "done": False})
        return {"ok": bool(t), "todo": t}

    @application.post("/api/todos/{uid}/toggle")
    def api_todo_toggle(uid: str):
        cid = _class_id()
        for t in data.records("todos", cid):
            if t["uid"] == uid:
                r = store.data.update("todos", uid, {"done": not t.get("done")}, cid, "manual")
                return {"ok": True, "done": r["done"]}
        return JSONResponse({"error": "not found"}, status_code=404)

    @application.post("/api/todos/{uid}/delete")
    def api_todo_delete(uid: str):
        cid = _class_id()
        return {"ok": store.remove("todos", uid, cid, "manual")}

    # ---------- 请假 ----------
    @application.post("/api/leaves")
    def api_leave_add(body: dict = Body(...)):
        cid = _class_id()
        sid_name = body.get("student", "").strip()
        s = store.get_student(cid, sid_name) if sid_name else None
        if sid_name and not s:
            return JSONResponse({"error": "学生不存在：%s，请先在花名册录入" % sid_name},
                                status_code=400)
        rec = store.add_leave(cid, {
            "student": s["name"] if s else sid_name,
            "student_id": s["student_id"] if s else "",
            "type": body.get("type") or "病假",
            "start_date": body.get("start_date") or data.today_str(),
            "days": int(body.get("days", 1) or 1),
            "reason": body.get("reason", ""),
            "attachment": bool(body.get("attachment")),
            "status": "已同意"})
        # end_date 计算存回（不重复记录日志）
        end = store._add_days(rec["start_date"], rec["days"] - 1)
        rec["end_date"] = end
        data.update("leaves", rec["uid"], {"end_date": end}, cid, "manual", undoable=False)
        return {"ok": True, "leave": rec}

    @application.get("/api/leaves")
    def api_leaves():
        return {"leaves": store.list_leaves(_class_id())}

    # ---------- 考勤 ----------
    @application.get("/api/attendance")
    def api_attendance(date: str = ""):
        cid = _class_id()
        d = date or data.today_str()
        return store.attendance_on(cid, d)

    @application.post("/api/attendance/mark")
    def api_attendance_mark(body: dict = Body(...)):
        cid = _class_id()
        s = store.get_student(cid, body.get("student", ""))
        if not s:
            return JSONResponse({"error": "学生不存在"}, status_code=400)
        store.mark_attendance(cid, {"date": body.get("date") or data.today_str(),
                                    "student_id": s["student_id"],
                                    "mark": body.get("mark", "旷课"),
                                    "reason": body.get("reason", "")})
        return {"ok": True}

    # ---------- 课表 ----------
    @application.get("/api/timetable")
    def api_timetable():
        return {"grid": store.timetable_grid(_class_id()), "entries": store.get_timetable(_class_id())}

    @application.post("/api/timetable")
    def api_timetable_save(body: dict = Body(...)):
        cid = _class_id()
        entries = body.get("entries", [])
        store.set_timetable(cid, entries, "manual")
        return {"ok": True, "count": len(entries)}

    # ---------- 通知 ----------
    @application.post("/api/notices")
    def api_notice_add(body: dict = Body(...)):
        cid = _class_id()
        n = store.add_notice(cid, {
            "title": body.get("title", ""), "content": body.get("content", ""),
            "audience": body.get("audience", "全体家长"), "status": "草稿",
            "published_at": "", "read_count": 0, "total": store.roster_stats(cid)["active"]})
        return {"ok": True, "notice": n}

    @application.post("/api/notices/{uid}/send")
    def api_notice_send(uid: str):
        cid = _class_id()
        r = store.data.update("notices", uid, {"status": "已发布",
                                              "published_at": data.now_str()}, cid, "manual")
        return {"ok": bool(r)}

    @application.post("/api/notices/{uid}/read")
    def api_notice_read(uid: str, body: dict = Body(...)):
        cid = _class_id()
        for n in data.records("notices", cid):
            if n["uid"] == uid:
                total = store.roster_stats(cid)["active"] or 1
                rc = int(body.get("read_count", n.get("read_count", 0)))
                store.data.update("notices", uid, {"read_count": min(rc + 1, total)},
                                  cid, "manual", undoable=False)
                return {"ok": True, "read_count": min(rc + 1, total)}
        return JSONResponse({"error": "not found"}, status_code=404)

    # ---------- 预警 ----------
    @application.post("/api/warnings")
    def api_warning_add(body: dict = Body(...)):
        cid = _class_id()
        w = store.add_warning(cid, {
            "student": body.get("student", ""), "kind": body.get("kind", "其他"),
            "level": body.get("level", "黄"), "desc": body.get("desc", ""),
            "resolved": False})
        return {"ok": bool(w), "warning": w}

    @application.post("/api/warnings/{uid}/resolve")
    def api_warning_resolve(uid: str):
        cid = _class_id()
        r = store.data.update("warnings", uid, {"resolved": True}, cid, "manual")
        return {"ok": bool(r)}

    # ---------- AI ----------
    @application.get("/api/ai/history")
    def api_ai_history():
        return {"messages": store.chat_history(_class_id())}

    @application.post("/api/ai/history/clear")
    def api_ai_clear():
        store.clear_chat(_class_id())
        return {"ok": True}

    @application.post("/api/ai/chat")
    def api_ai_chat(body: dict = Body(...)):
        cid = _class_id()
        text = (body.get("text") or "").strip()
        if not text:
            return JSONResponse({"error": "空内容"}, status_code=400)
        cfg = data.load_config()
        if not cfg["ai"].get("api_key"):
            return {"intent": "chat", "reply": "请先在「设置」中填入 DeepSeek API Key（仅存本机）。",
                    "questions": [], "actions": []}
        r = ai.build_actions_reply(cfg, text)
        store.append_chat(cid, {"role": "user", "content": text, "ts": data.now_str()})
        store.append_chat(cid, {"role": "assistant", "content": text and r.get("reply") or "",
                                "intent": r.get("intent"), "ts": data.now_str()})
        return r

    @application.post("/api/ai/confirm")
    def api_ai_confirm(body: dict = Body(...)):
        """执行前端回传的 action 列表（用户已在确认卡片点确认）。"""
        cid = _class_id()
        results, warnings_created = [], []
        for act in body.get("actions", []):
            t = act.get("type")
            p = act.get("payload") or act
            try:
                if t == "add_leave":
                    s = store.get_student(cid, p.get("student", ""))
                    if not s:
                        results.append({"ok": False, "msg": "学生不存在：%s" % p.get("student")})
                        continue
                    days = int(p.get("days", 1) or 1)
                    rec = store.add_leave(cid, {
                        "student": s["name"], "student_id": s["student_id"],
                        "type": p.get("type") or "病假",
                        "start_date": p.get("start_date") or data.today_str(),
                        "days": days, "reason": p.get("reason", ""),
                        "attachment": bool(p.get("attachment")), "status": "已同意"})
                    end = store._add_days(rec["start_date"], days - 1)
                    rec["end_date"] = end
                    data.update("leaves", rec["uid"], {"end_date": end}, cid, "manual", undoable=False)
                    results.append({"ok": True, "msg": "已登记：%s %s %s起%d天 ✔ 考勤已联动" % (
                        s["name"], rec["type"], rec["start_date"], days)})
                    if data.load_config()["settings"].get("leave_notify_parent") and s.get("parent_phone"):
                        results.append({"ok": True, "msg": "📋 已生成家长告知草稿（见通知中心）"})
                        store.add_notice(cid, {"title": "家长告知：%s" % s["name"],
                                               "content": "【%s家长您好，%s今日%s（%s～%s，%d天），原因：%s。请留意孩子返校时间。】" % (
                                                   s["name"], rec["type"], rec["start_date"],
                                                   end, days, rec.get("reason", "")),
                                               "audience": "家长：%s(%s)" % (s["name"], s.get("parent_name", "")),
                                               "status": "草稿", "published_at": "",
                                               "read_count": 0,
                                               "total": store.roster_stats(cid)["active"]})
                elif t == "add_todo":
                    store.add_todo(cid, {"title": p.get("title", ""), "due": p.get("due", ""),
                                         "time": p.get("time", ""), "category": p.get("category") or "班级管理",
                                         "priority": p.get("priority") or "中", "done": False})
                    results.append({"ok": True, "msg": "待办已创建 ✔ 将出现在顶部提醒与首页看板"})
                elif t == "complete_todo":
                    kw = act.get("keyword") or p.get("keyword") or ""
                    done = 0
                    for td in store.list_todos(cid):
                        if kw and kw in td.get("title", ""):
                            data.update("todos", td["uid"], {"done": True}, cid, "manual")
                            done += 1
                            break
                    results.append({"ok": done > 0,
                                    "msg": "已完成✔" if done else "没找到包含「%s」的待办" % kw})
                elif t == "mark_attendance":
                    s = store.get_student(cid, p.get("student", ""))
                    if not s:
                        results.append({"ok": False, "msg": "学生不存在：%s" % p.get("student")})
                        continue
                    store.mark_attendance(cid, {"date": p.get("date") or data.today_str(),
                                                "student_id": s["student_id"],
                                                "mark": p.get("mark") or "旷课",
                                                "reason": p.get("reason", "")}, "ai")
                    results.append({"ok": True, "msg": "已登记 %s %s ✔ 首页到校已更新" % (
                        s["name"], p.get("mark") or "旷课")})
                elif t == "add_tag":
                    s = store.get_student(cid, act.get("student") or p.get("student", ""))
                    if s:
                        store.set_tag(cid, s["student_id"], act.get("tag") or p.get("tag", ""), True)
                        results.append({"ok": True, "msg": "已为 %s 添加标签 ✔" % s["name"]})
                    else:
                        results.append({"ok": False, "msg": "学生不存在"})
                elif t == "add_warning":
                    w = store.add_warning(cid, {"student": p.get("student", ""),
                                                "kind": p.get("kind", "其他"),
                                                "level": p.get("level", "黄"),
                                                "desc": p.get("desc", ""), "resolved": False})
                    results.append({"ok": True, "msg": "预警已记录 ✔ 首页红黄灯已更新"})
                elif t == "update_student":
                    s = store.get_student(cid, act.get("student") or p.get("student", ""))
                    if s:
                        data.update("students", s["uid"], {act.get("field") or p.get("field"):
                                                           act.get("value") or p.get("value")}, cid, "ai")
                        results.append({"ok": True, "msg": "%s 信息已更新 ✔" % s["name"]})
                    else:
                        results.append({"ok": False, "msg": "学生不存在"})
                elif t == "gen_notice":
                    draft = ai.draft_notice(data.load_config(), p.get("title", ""),
                                            p.get("audience", "全体家长"), p.get("key_points", ""))
                    n = store.add_notice(cid, {"title": p.get("title", ""), "content": draft,
                                               "audience": p.get("audience", "全体家长"),
                                               "status": "草稿", "published_at": "",
                                               "read_count": 0,
                                               "total": store.roster_stats(cid)["active"]})
                    results.append({"ok": True, "msg": "通知草稿已生成（见通知中心），可复制发群 ✔"})
                elif t == "save_grades":
                    rows, unknown = [], []
                    for it in p.get("items", []):
                        s = store.get_student(cid, str(it.get("name", "")))
                        try:
                            score = float(it.get("score"))
                        except Exception:
                            score = None
                        if s and score is not None:
                            rows.append({"student_id": s["student_id"], "name": s["name"], "score": score})
                        else:
                            unknown.append(it.get("name"))
                    if unknown:
                        results.append({"ok": False, "msg": "学生不存在，未写入：%s" % "、".join(map(str, unknown[:5]))})
                    if rows:
                        try:
                            rec, created = features.save_grade_sheet(cid, {
                                "exam": p.get("exam", ""), "subject": p.get("subject", ""),
                                "full": p.get("full") or 100, "date": p.get("date") or "",
                                "items": rows}, "ai")
                            raised = features.run_grade_rules(cid, "auto")
                            msg = "成绩已%s ✔（%d 人 · %s·%s）" % (
                                "录入" if created else "更新", len(rows),
                                rec.get("exam"), rec.get("subject"))
                            if raised:
                                msg += " 触发学业预警：" + "；".join(raised[:3])
                            results.append({"ok": True, "msg": msg + " → 见「学业与成绩→学业分析」"})
                        except ValueError as e:
                            results.append({"ok": False, "msg": str(e)})
                elif t == "setup_semester":
                    before = data.snapshot_config()
                    try:
                        cur = features.add_semester(cid, {
                            "name": p.get("name", ""), "start": p.get("start", ""),
                            "weeks_n": p.get("weeks_n", "")}, "ai")
                        data.log_config(before, "ai")
                        results.append({"ok": True, "msg": "新学期「%s」已设置 ✔（开学 %s）。请接着完成：设置→校历 点选上课日；首页→编辑课表 录入本学期课表。" % (
                            cur["active"], p.get("start") or "未填")})
                    except ValueError as e:
                        results.append({"ok": False, "msg": str(e)})
                elif t == "set_timetable":
                    entries = act.get("entries") or []
                    old = store.get_timetable(cid)
                    store.set_timetable(cid, entries, "ai")
                    results.append({"ok": True, "msg": "课表已写入 ✔（%d 格，原 %d 格可撤销恢复）→ 首页本周课表" % (
                        len(entries), len(old))})
                else:
                    results.append({"ok": False, "msg": "未知操作 %s" % t})
            except Exception as e:
                results.append({"ok": False, "msg": "执行失败：%s" % str(e)[:100]})
        return {"results": results}

    # ---------- 二期：校时 / 校历 / 备份 / 迁移 ----------
    @application.get("/api/time")
    def api_time():
        """联网校时：仅请求公开时间接口，不发送任何本地数据。"""
        import datetime as _dt
        for url, parse in (
            ("https://acs.m.taobao.com/gw/mtop.common.getTimestamp/",
             lambda j: _dt.datetime.fromtimestamp(int(j["data"]["t"]) / 1000)),
            ("https://worldtimeapi.org/api/timezone/Asia/Shanghai",
             lambda j: _dt.datetime.fromisoformat(j["datetime"][:19])),
        ):
            try:
                r = httpx.get(url, timeout=2.5)
                r.raise_for_status()
                dt = parse(r.json())
                return {"ok": True, "source": "net",
                        "now": dt.strftime("%Y-%m-%d %H:%M:%S")}
            except Exception:
                continue
        return {"ok": True, "source": "local", "now": data.now_str()}

    @application.get("/api/calendar")
    def api_calendar():
        cid = _class_id()
        cal = features.get_calendar(cid)
        label, src = features.week_of(cid)
        return {"calendar": cal, "week_label": label, "week_source": src,
                "today": data.today_str()}

    @application.post("/api/calendar")
    def api_calendar_save(body: dict = Body(...)):
        cid = _class_id()
        if body.get("mode") == "days":
            features.set_calendar_days(cid, body.get("class_days") or [], "manual")
        else:
            features.set_calendar(cid, body.get("calendar") or {}, "manual")
        return {"ok": True}

    # ---------- 新学期 / 学期档案 ----------
    @application.get("/api/semesters")
    def api_semesters():
        return features.get_semesters(_class_id())

    @application.post("/api/semester/new")
    def api_semester_new(body: dict = Body(...)):
        cid = _class_id()
        before = data.snapshot_config()
        try:
            cur = features.add_semester(cid, {
                "name": body.get("name", ""), "start": body.get("start", ""),
                "weeks_n": body.get("weeks_n", "")}, "manual")
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        data.log_config(before, "semester")
        return {"ok": True, "active": cur["active"],
                "msg": "新学期「%s」已设为当前，请完善校历与课表" % cur["active"]}

    # ---------- 宿舍管理 ----------
    @application.get("/api/dorm")
    def api_dorm():
        return features.dorm_view(_class_id())

    @application.post("/api/dorm/room")
    def api_dorm_room(body: dict = Body(...)):
        cid = _class_id()
        name = (body.get("room") or "").strip()
        if not name:
            return JSONResponse({"error": "房间号必填"}, status_code=400)
        features.upsert_room(cid, name, body.get("building"), body.get("beds"),
                             body.get("gender"))
        return {"ok": True}

    @application.post("/api/dorm/room/delete")
    def api_dorm_room_del(body: dict = Body(...)):
        cid = _class_id()
        name = (body.get("room") or "").strip()
        view = features.dorm_view(cid)
        r = next((x for x in view["rooms"] if x["room"] == name), None)
        if r and r["filled"]:
            return JSONResponse({"error": "该房间还有 %d 人就寝，请先安置学生（改宿舍号或换房）" % r["filled"],
                                 "has_people": True}, status_code=400)
        features.delete_room(cid, name)
        return {"ok": True}

    @application.post("/api/dorm/assign")
    def api_dorm_assign2(body: dict = Body(...)):
        cid = _class_id()
        try:
            msg = features.assign_bed(cid, (body.get("room") or "").strip(),
                                      body.get("bed", 0), body.get("student", ""))
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return {"ok": True, "msg": msg}

    @application.post("/api/dorm/import_beds")
    async def api_dorm_import_beds(file: UploadFile = File(...)):
        cid = _class_id()
        tmp = os.path.join(data.EXCEL_DIR, "beds_" + os.path.basename(file.filename or "beds.xlsx"))
        content = await file.read()
        with open(tmp, "wb") as f:
            f.write(content)
        try:
            grid = office._load_sheet_rows(tmp)
        except Exception as e:
            return JSONResponse({"error": "读取失败：%s" % str(e)[:120]}, status_code=400)
        rows = []
        for r in grid[1:]:
            if len(r) >= 3 and (r[0].strip() or r[2].strip()):
                rows.append({"room": r[0].strip(), "bed": r[1].strip() or 1,
                             "student": r[2].strip()})
        if not rows:
            return JSONResponse({"error": "未解析到床位数据（首行需表头：房间/床号/学号姓名）"},
                                status_code=400)
        result = features.import_beds(cid, rows)
        try:
            os.remove(tmp)
        except Exception:
            pass
        return result

    @application.post("/api/dorm/hygiene_import")
    async def api_dorm_hygiene_import(file: UploadFile = File(...)):
        """批量导入卫生评分：列为 日期/房间/分数/备注(可空)。"""
        cid = _class_id()
        tmp = os.path.join(data.EXCEL_DIR, "hy_" + os.path.basename(file.filename or "hy.xlsx"))
        content = await file.read()
        with open(tmp, "wb") as f:
            f.write(content)
        try:
            grid = office._load_sheet_rows(tmp)
        except Exception as e:
            return JSONResponse({"error": "读取失败：%s" % str(e)[:120]}, status_code=400)
        # 定位表头列
        hi, cols = -1, {}
        for ri, r in enumerate(grid[:6]):
            m = {}
            for ci, cell in enumerate(r):
                t = cell.replace(" ", "")
                if "日期" in t or t.lower() == "date":
                    m["date"] = ci
                elif "房间" in t or "宿舍" in t:
                    m["room"] = ci
                elif "分" in t:
                    m["score"] = ci
                elif "备注" in t or "说明" in t:
                    m["note"] = ci
            if "room" in m and "score" in m:
                hi, cols = ri, m
                break
        if hi < 0:
            return JSONResponse({"error": "未识别表头（需含 房间、分数 列，日期/备注可选）"}, status_code=400)
        n, fails = 0, []
        for r in grid[hi + 1:]:
            try:
                room = str(r[cols["room"]]).strip()
                score = float(r[cols["score"]])
                if not room:
                    continue
                date = str(r[cols.get("date", 0)]).strip() if "date" in cols and len(r) > cols["date"] else ""
                if date in ("", "日期"):
                    date = data.today_str()
                note = str(r[cols.get("note", 0)]).strip() if "note" in cols and len(r) > cols["note"] else ""
                features.add_hygiene(cid, room, date, score, note, "import")
                n += 1
            except Exception:
                continue
        try:
            os.remove(tmp)
        except Exception:
            pass
        return {"ok": n}

    @application.post("/api/dorm/notice")
    def api_dorm_notice():
        r = features.dorm_notice(_class_id())
        if r.get("error"):
            return JSONResponse({"error": r["error"]}, status_code=400)
        return r

    @application.post("/api/dorm/export")
    def api_dorm_export():
        cid = _class_id()
        view = features.dorm_view(cid)
        p = os.path.join(data.EXCEL_DIR, "宿舍分配_%s.xlsx" % time.strftime("%Y%m%d_%H%M%S"))
        office.export_dorm_xlsx(view, p)
        return FileResponse(p, filename=os.path.basename(p))

    @application.post("/api/dorm/hygiene")
    def api_dorm_hygiene(body: dict = Body(...)):
        cid = _class_id()
        room = (body.get("room") or "").strip()
        if not room:
            return JSONResponse({"error": "房间号必填"}, status_code=400)
        lst = features.add_hygiene(cid, room, body.get("date") or data.today_str(),
                                   body.get("score", 0), body.get("note", ""))
        return {"ok": True, "history": lst}

    @application.post("/api/dorm/hygiene/delete")
    def api_dorm_hygiene_del(body: dict = Body(...)):
        cid = _class_id()
        obj = data.get_obj("dorm", {}) or {}
        d = obj.get(cid, {})
        room = body.get("room", "")
        uid = body.get("uid", "")
        if room in d:
            d[room] = [x for x in d[room] if x.get("uid") != uid]
            data.set_obj("dorm", obj, "manual")
        return {"ok": True}



    # ---------- 评优与评奖 ----------
    @application.get("/api/awards")
    def api_awards():
        cid = _class_id()
        return {"stats": features.award_stats(cid),
                "records": [a for a in sorted(data.records("awards", cid),
                                              key=lambda r: r.get("date", ""), reverse=True)]}

    @application.post("/api/awards")
    def api_award_add(body: dict = Body(...)):
        cid = _class_id()
        if not (body.get("student") or "").strip():
            return JSONResponse({"error": "学生姓名必填"}, status_code=400)
        rec = data.insert("awards", dict(body), cid, "manual")
        return {"ok": True, "item": rec}

    @application.post("/api/awards/{uid}/delete")
    def api_award_del(uid: str):
        return {"ok": data.remove("awards", uid, _class_id(), "manual")}

    # ---------- 帮助 ----------
    DEFAULT_HELP_MD = """# 班主任小助手 · 使用说明

## 快速上手（每天 3 件事）
1. **早上** 看首页「今日日程」与「待办看板」，逾期任务标红优先处理
2. **随手记** 把事说给右侧 AI 助手：请假、待办、记考勤、写通知、录成绩，确认后自动入库并联动
3. **下班前** 「个人工作」写两句日志，周日会自动进待办提醒你交周志

## 常用流程
- **导入花名册**：花名册 → 导入 Excel（首行需有 学号/姓名 等列名）
- **录成绩**：学业与成绩 → 成绩录入，每行"学号或姓名 分数"；保存后自动及格率/排名/学业预警
- **排值日/宿舍**：宿舍管理页按房间看名单、记卫生分（量化考核自动汇总）
- **新学期**：设置 → 班级与学期 → 「新学期设置」，或对 AI 说"下学期从 3 月 2 日开始"
- **校历**：设置 → 校历 → 点选上课日期，首页自动显示"第几周"
- **课表**：首页课表卡 → 编辑课表；支持粘贴文本、导入全学期课表 Excel（AI 整理成每周课表）
- **评优评奖**：按成绩综合排名自动生成奖学金预分名单，奖励/处分记录留档
- **换电脑**：设置 → 导出全部数据(JSON)，在新电脑导入即可

## 数据安全
- 全部数据存本机（位置见 设置→数据备份与迁移），**不上传云端**
- AI 对话仅把你的输入发给所选大模型服务商；写入前弹确认卡，写后留操作日志
- 每次写入前自动快照备份到 `files\\backups\\`；「撤销上一次写入」可回退
"""

    @application.get("/api/help")
    def api_help():
        obj = data.get_obj("help", {}) or {}
        md = (obj.get("obj") or {}).get("text") or DEFAULT_HELP_MD
        return {"markdown": md}

    @application.post("/api/help")
    def api_help_save(body: dict = Body(...)):
        data.set_obj("help", {"text": body.get("markdown", "")}, "manual")
        return {"ok": True}

    @application.post("/api/help/reset")
    def api_help_reset():
        data.set_obj("help", {"text": DEFAULT_HELP_MD}, "manual")
        return {"ok": True}

    # ---------- 课表导入增强 ----------
    @application.post("/api/timetable/parse_text")
    def api_tt_parse_text(body: dict = Body(...)):
        entries, skipped = features.parse_timetable_text(body.get("text", ""))
        return {"entries": entries, "skipped": skipped[:10], "count": len(entries)}

    def _do_import_timetable(path):
        """课表导入核心：规则解析优先，失败走 AI 深度理解；成功则入库并留存副本。
        返回 (result_dict, http_status)。"""
        cid = _class_id()
        method = "规则"
        try:
            entries = office.parse_timetable_xlsx(path)
        except Exception:
            cfg = data.load_config()
            if not cfg["ai"].get("api_key"):
                return ({"error": "课表格式复杂需 AI 理解，请先在设置中配置 API Key；或改用「粘贴课表文本」导入"}, 400)
            try:
                entries = ai.extract_timetable(cfg, office.timetable_raw_text(path))
                method = "AI 深度理解"
            except Exception as e:
                return ({"error": "AI 整理课表失败：%s" % str(e)[:150]}, 400)
        if not entries:
            return ({"error": "未能从文件中识别出课程"}, 400)
        store.set_timetable(cid, entries, "ai")
        import shutil
        try:
            dst = os.path.join(data.EXCEL_DIR, "本学期课表_%s.xlsx" % time.strftime("%Y%m%d_%H%M%S"))
            if os.path.abspath(path) != os.path.abspath(dst):
                shutil.copy2(path, dst)
            saved_path = dst
        except Exception:
            saved_path = ""
        return ({"count": len(entries), "entries": entries, "method": method,
                 "saved_path": saved_path}, 200)

    @application.post("/api/timetable/parse_excel")
    def api_tt_parse_excel(body: dict = Body(...)):
        path = (body.get("path") or "").strip()
        if not path or not os.path.isfile(path):
            return JSONResponse({"error": "文件不存在：%s（请确认路径）" % path}, status_code=400)
        result, code = _do_import_timetable(path)
        return JSONResponse(result, status_code=code)

    @application.post("/api/timetable/upload")
    async def api_tt_upload(file: UploadFile = File(...)):
        name = os.path.basename((file.filename or "课表.xlsx").replace("\\", "/"))
        name = "".join(c for c in name if c not in '\\/:*?"<>|').strip() or "课表.xlsx"
        if not name.lower().endswith((".xlsx", ".xlsm", ".xls")):
            return JSONResponse({"error": "请选择 .xlsx 或 .xls 课表文件"}, status_code=400)
        content = await file.read()
        if len(content) > 10 * 1024 * 1024:
            return JSONResponse({"error": "文件过大（限 10MB）"}, status_code=400)
        tmp = os.path.join(data.EXCEL_DIR, "timetable_upload_" + name)
        with open(tmp, "wb") as f:
            f.write(content)
        result, code = _do_import_timetable(tmp)
        try:
            os.remove(tmp)   # 临时上传文件用完即删（留档副本已由 _do_import_timetable 另存）
        except Exception:
            pass
        result["filename"] = name
        return JSONResponse(result, status_code=code)


    @application.get("/api/backup/export")
    def api_backup_export():
        cid = _class_id()
        cfg = data.load_config()
        export_cfg = {"class": cfg["class"], "semester": cfg["semester"],
                      "settings": cfg["settings"],
                      "ai": {k: cfg["ai"].get(k) for k in ("provider", "base_url", "model")}}
        files = {}
        dd = data.data_dir()
        if os.path.isdir(dd):
            for fn in sorted(os.listdir(dd)):
                if fn.endswith(".json"):
                    try:
                        with open(os.path.join(dd, fn), "r", encoding="utf-8") as f:
                            files[fn] = json.load(f)
                    except Exception:
                        pass
        payload = {"app": "banzhuren-workbench", "version": 2,
                   "exported_at": data.now_str(), "config": export_cfg, "data": files}
        tmp = os.path.join(data.files_dir(), "班级数据备份_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        return FileResponse(tmp, filename=os.path.basename(tmp))

    @application.post("/api/backup/import")
    async def api_backup_import(file: UploadFile = File(...)):
        content = await file.read()
        try:
            payload = json.loads(content.decode("utf-8"))
        except Exception:
            return JSONResponse({"error": "不是有效的备份 JSON 文件"}, status_code=400)
        if payload.get("app") != "banzhuren-workbench" or "data" not in payload:
            return JSONResponse({"error": "文件格式不符（需要本系统导出的备份文件）"}, status_code=400)
        data.ensure_dirs()
        for fn, obj in payload["data"].items():
            if not fn.endswith(".json") or fn == "config.json":
                continue
            with open(os.path.join(data.data_dir(), fn), "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=1)
        cfg = data.load_config()
        imp = payload.get("config") or {}
        for sec in ("class", "semester", "settings"):
            if isinstance(imp.get(sec), dict):
                cfg[sec].update({k: v for k, v in imp[sec].items() if v not in (None, "")})
        for k in ("provider", "base_url", "model"):
            if imp.get("ai", {}).get(k):
                cfg["ai"][k] = imp["ai"][k]
        data.save_config(cfg)
        return {"ok": True, "files": len(payload["data"]),
                "msg": "导入完成（当前数据已自动快照备份）"}

    @application.post("/api/storage/move")
    def api_storage_move(body: dict = Body(...)):
        new_root = (body.get("path") or "").strip()
        if not new_root:
            return JSONResponse({"error": "请填写新的数据文件夹路径"}, status_code=400)
        new_root = os.path.abspath(new_root)
        try:
            os.makedirs(new_root, exist_ok=True)
            probe = os.path.join(new_root, ".write_test")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            import shutil as _sh
            for sub in ("data", "files"):
                src = data.data_dir() if sub == "data" else data.files_dir()
                dst = os.path.join(new_root, sub)
                if os.path.isdir(src):
                    if os.path.abspath(src) != os.path.abspath(dst):
                        if os.path.isdir(dst):
                            _sh.rmtree(dst)
                        _sh.copytree(src, dst)
        except Exception as e:
            return JSONResponse({"error": "迁移失败：%s" % str(e)[:200]}, status_code=500)
        cfg = data.load_config()
        cfg.setdefault("storage", {})["data_dir"] = new_root
        data.save_config(cfg)
        return {"ok": True, "data_dir": data.data_dir(),
                "msg": "已迁移，数据现保存于 " + data.data_dir() + "（建议重启服务）"}

    # ---------- 二期：成绩 / 台账 / 画像 ----------
    @application.post("/api/grades")
    def api_grades_save(body: dict = Body(...)):
        cid = _class_id()
        try:
            rec, created = features.save_grade_sheet(cid, body)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        raised = features.run_grade_rules(cid, "auto")
        return {"ok": True, "created": created, "warnings_raised": raised}

    @application.get("/api/grades")
    def api_grades_list(q: str = ""):
        cid = _class_id()
        gs = data.records("grades", cid)
        if q:
            gs = [g for g in gs if q in (g.get("exam", "") + g.get("subject", ""))]
        gs.sort(key=lambda g: g.get("date", ""), reverse=True)
        return {"sheets": gs}

    @application.post("/api/grades/{uid}/delete")
    def api_grades_delete(uid: str):
        return {"ok": data.remove("grades", uid, _class_id(), "manual")}

    @application.get("/api/grades/analysis")
    def api_grades_analysis(exam: str = "", subject: str = ""):
        a = features.grade_analysis(_class_id(), exam or None, subject or None)
        return {"analysis": a}

    LEDGERS = {"internships": "实习", "family": "家校", "talks": "谈心",
               "activities": "活动", "quant": "量化", "awards": "奖惩"}

    def _ledger_ok(name):
        if name in LEDGERS or name.startswith("ext_"):
            return True
        return False

    # ---------- 扩展模块（用户自定义） ----------
    @application.get("/api/ext")
    def api_ext_list():
        cid = _class_id()
        obj = data.get_obj("ext", {}) or {}
        mods = [m for m in obj.get(cid, []) if not m.get("disabled")]
        return {"modules": mods}

    @application.post("/api/ext")
    def api_ext_save(body: dict = Body(...)):
        cid = _class_id()
        name = (body.get("name") or "").strip()
        fields = [f for f in (body.get("fields") or [])
                  if isinstance(f, dict) and (f.get("label") or "").strip()]
        if not name or not fields:
            return JSONResponse({"error": "模块名称与至少一个字段必填"}, status_code=400)
        if len(name) > 12:
            return JSONResponse({"error": "模块名称请控制在 12 字以内"}, status_code=400)
        obj = data.get_obj("ext", {}) or {}
        mods = obj.setdefault(cid, [])
        mid = body.get("id") or ("m" + uuid.uuid4().hex[:6])
        norm = [{"key": ("f%d" % i), "label": (f.get("label") or "").strip()[:12],
                 "type": f.get("type") if f.get("type") in ("text", "number", "date") else "text"}
                for i, f in enumerate(fields)]
        target = next((m for m in mods if m.get("id") == mid), None)
        if target:
            target["name"], target["fields"] = name, norm
        else:
            mods.append({"id": mid, "name": name, "fields": norm, "created_at": data.now_str()})
        data.set_obj("ext", obj, "manual")
        return {"ok": True, "id": mid}

    @application.post("/api/ext/{mid}/delete")
    def api_ext_delete(mid: str):
        cid = _class_id()
        obj = data.get_obj("ext", {}) or {}
        mods = obj.get(cid, [])
        obj[cid] = [m for m in mods if m.get("id") != mid]
        data.set_obj("ext", obj, "manual")
        return {"ok": True}

    @application.get("/api/ledger/{name}")
    def api_ledger_list(name: str):
        if not _ledger_ok(name):
            return JSONResponse({"error": "unknown ledger"}, status_code=404)
        cid = _class_id()
        ls = data.records(name, cid)
        ls.sort(key=lambda r: r.get("date") or r.get("created_at") or "", reverse=True)
        return {"items": ls}

    @application.post("/api/ledger/{name}")
    def api_ledger_add(name: str, body: dict = Body(...)):
        if not _ledger_ok(name):
            return JSONResponse({"error": "unknown ledger"}, status_code=404)
        rec = data.insert(name, dict(body), _class_id(), "manual")
        return {"ok": True, "item": rec}

    @application.post("/api/ledger/{name}/{uid}/delete")
    def api_ledger_del(name: str, uid: str):
        if not _ledger_ok(name):
            return JSONResponse({"error": "unknown ledger"}, status_code=404)
        return {"ok": data.remove(name, uid, _class_id(), "manual")}

    @application.get("/api/culture")
    def api_culture_get():
        obj = data.get_obj("culture", {}) or {}
        return {"rules": (obj.get(_class_id()) or {}).get("rules", "")}

    @application.post("/api/culture")
    def api_culture_save(body: dict = Body(...)):
        cid = _class_id()
        obj = data.get_obj("culture", {}) or {}
        obj.setdefault(cid, {})["rules"] = body.get("rules", "")
        data.set_obj("culture", obj, "manual")
        return {"ok": True}

    @application.get("/api/grades/exams")
    def api_grades_exams():
        return {"exams": features.exam_list(_class_id())}

    @application.get("/api/grades/report")
    def api_grades_report(exam: str = ""):
        cid = _class_id()
        if not exam:
            es = features.exam_list(cid)
            exam = es[0]["exam"] if es else ""
        return {"report": features.grade_report(cid, exam) if exam else None,
                "exams": features.exam_list(cid), "exam": exam}

    @application.post("/api/grades/report/export")
    def api_grades_report_export(body: dict = Body(...)):
        cid = _class_id()
        exam = body.get("exam") or ""
        rep = features.grade_report(cid, exam)
        if not rep:
            return JSONResponse({"error": "该考试暂无成绩数据"}, status_code=400)
        p = os.path.join(data.WORD_DIR, "学业分析_%s_%s.docx" % (exam, time.strftime("%Y%m%d_%H%M%S")))
        office.export_grade_report_docx(cid, rep, p)
        return FileResponse(p, filename=os.path.basename(p))

    @application.get("/api/worklog")
    def api_worklog(date: str = ""):
        cid = _class_id()
        d = date or data.today_str()
        cur = [w for w in data.records("worklog", cid) if w.get("date") == d]
        ls = sorted(data.records("worklog", cid), key=lambda w: w.get("date", ""), reverse=True)
        return {"current": cur[0] if cur else None, "date": d, "recent": ls[:30]}

    @application.post("/api/worklog")
    def api_worklog_save(body: dict = Body(...)):
        cid = _class_id()
        d = body.get("date") or data.today_str()
        existing = [w for w in data.records("worklog", cid) if w.get("date") == d]
        payload = {"date": d, "done": body.get("done", ""), "problem": body.get("problem", ""),
                   "plan": body.get("plan", "")}
        if existing:
            data.update("worklog", existing[0]["uid"], payload, cid, "manual")
        else:
            data.insert("worklog", payload, cid, "manual")
        return {"ok": True}

    @application.get("/api/stats")
    def api_stats():
        return features.class_portrait(_class_id())

    # ---------- 系统 ----------
    @application.post("/api/undo")
    def api_undo():
        ok, msg = data.undo_last()
        return JSONResponse({"ok": ok, "msg": msg}, status_code=200 if ok else 400)

    @application.get("/api/ops")
    def api_ops():
        path = data._data_path("ops_log")
        try:
            import json as _json
            with open(path, "r", encoding="utf-8") as f:
                ops = _json.load(f)
            return {"ops": ops[-30:][::-1]}
        except Exception:
            return {"ops": []}

    @application.get("/api/backup/list")
    def api_backup_list():
        out = []
        d = data.BACKUP_DIR
        if os.path.isdir(d):
            for day in sorted(os.listdir(d), reverse=True)[:7]:
                dd = os.path.join(d, day)
                if os.path.isdir(dd):
                    files = os.listdir(dd)
                    out.append({"date": day, "count": len(files),
                                "files": sorted(files, reverse=True)[:10]})
        return {"backups": out}

    # ---------- 静态前端（必须最后挂载，否则会拦截 /api 路由） ----------
    data.ensure_dirs()  # 首次运行（出厂状态）时 files/ 尚不存在，先建好再挂载
    application.mount("/files", StaticFiles(directory=data.FILES_DIR), name="files")
    application.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

    return application


data.ensure_dirs()
app = create_app()


def main():
    data.ensure_dirs()
    def _open():
        time.sleep(1.2)
        try:
            webbrowser.open("http://127.0.0.1:%d" % PORT)
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
