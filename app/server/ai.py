# -*- coding: utf-8 -*-
"""AI 层：DeepSeek（OpenAI 兼容接口）。负责把自然语言转成结构化操作建议。
API Key 只存本地 config.json。
"""
import json

import httpx

from . import data, store

SYSTEM_PROMPT = """你是一个高职班主任工作台的 AI 助手，工作目录在学生本地电脑。
你的任务：理解班主任输入的自然语言，把它转换成对本地数据库的操作建议。

可执行的操作类型（intent）及字段：
1. add_leave 登记请假：student(姓名), type(病假/事假/其他), start_date(YYYY-MM-DD), days(数字), reason, has_attachment(是否附请假条)
2. add_todo 新建待办/提醒：title, due(YYYY-MM-DD), time(HH:MM，可无), category(教学/班级管理/行政事务), priority(高/中/低)
3. complete_todo 完成待办：keyword(用于在学生待办列表里找标题)
4. mark_attendance 考勤异常登记：student, date(YYYY-MM-DD，默认今天), mark(旷课/迟到/早退), reason
5. add_tag 给学生加标签：student, tag(留守/单亲/学困/退役士兵/建档立卡/心理关注/班委/竞赛/全勤/偏科/临界)
6. add_warning 记录预警：student, kind(学业/心理/违纪/考勤/其他), level(红/黄), desc
7. update_student 修改学生信息：student, field(可改字段:gender/birth/origin/dorm/parent_name/parent_phone/address/status/remark), value
8. gen_notice 生成通知文本：title, audience(全体家长/班委/指定学生), key_points
9. save_grades 批量录成绩：exam(考试名称), subject(科目), items(数组，元素为"姓名 分数"字符串或{student,name,score}；从用户给的名单逐条提取), full(满分，默认100), date(YYYY-MM-DD，可无)
10. setup_semester 新学期设置：name(学期名称，如"2026-2027学年第一学期"), start(开学日期YYYY-MM-DD), weeks_n(总周数，可无)。当用户说"开始新学期/下学期从X月X日开始"时使用。设置后系统会提醒完善校历和课表。
11. set_timetable 登记课表：entries(数组，元素为"周X,节次,课程"字符串，如"周一,1-2节,高等数学"；节次用 1-2节/3-4节/5-6节/晚自习)。用户口述一周课表或粘贴课表文本时使用。

查询类意图（只回答，不写库）：
- query_student 查学生信息：student
- query_roster 查花名册统计（人数/男女/标签分布）
- query_leave 查某学生请假记录：student
- query_todo 查待办
- help 帮助说明

重要规则：
- 如果用户没有明确日期，今天= {today}，周{weekday}。把"明天/下周五"等相对时间换算成具体日期。
- 意图不明确时，选最可能的操作，并在 questions 里提醒用户核对。
- 纯打招呼/提问 → intent 用 "chat"，直接 reply 回答。

你必须严格输出 JSON（不要输出任何其他文字）：
{"intent": "...", "args": {...}, "reply": "给人看的简短中文说明",
 "questions": ["如有需要用户确认的点写在这里，可为空数组"]}
只输出这一个 JSON 对象。"""


def chat(messages, config=None):
    """messages: [{role, content}...]。返回 {intent,args,reply,questions}。"""
    cfg = config or data.load_config()
    ai = cfg["ai"]
    today = data.today_str()
    weekday = store._week_cn(today)[-1]
    sys_prompt = SYSTEM_PROMPT.replace("{today}", today).replace("{weekday}", weekday)
    payload = {
        "model": ai.get("model") or "deepseek-flash",
        "messages": [{"role": "system", "content": sys_prompt}] + messages[-12:],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": "Bearer " + ai.get("api_key", ""),
        "Content-Type": "application/json",
    }
    url = ai.get("base_url", "").rstrip("/") + "/chat/completions"
    timeout = ai.get("timeout", 60)
    try:
        r = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        r.raise_for_status()
        j = r.json()
        content = j["choices"][0]["message"]["content"]
        result = json.loads(content)
    except httpx.HTTPStatusError as e:
        return _fallback("API 返回错误 %s：%s" % (e.response.status_code, e.response.text[:200]))
    except Exception as e:
        return _fallback("AI 调用失败：" + str(e)[:200])
    # 规范化
    if not isinstance(result, dict):
        return _fallback("AI 返回格式异常")
    result.setdefault("intent", "chat")
    result.setdefault("args", {})
    result.setdefault("reply", "")
    result.setdefault("questions", [])
    return result


WRITE_INTENTS = {"add_leave", "add_todo", "complete_todo", "mark_attendance",
                 "add_tag", "add_warning", "update_student", "save_grades",
                 "setup_semester", "set_timetable", "gen_notice"}


def _fallback(msg):
    return {"intent": "chat", "args": {}, "reply": msg, "questions": []}


def build_actions_reply(cfg, text):
    """先做意图识别，再生成可直接落库的 action 列表。供 /api/ai/parse 用。"""
    r = chat([{"role": "user", "content": text}], cfg)
    intent = r.get("intent")
    args = r.get("args") or {}
    actions = []
    today = data.today_str()

    if intent == "add_leave" and args.get("student"):
        days = args.get("days") or 1
        try:
            days = max(1, int(days))
        except Exception:
            days = 1
        actions.append({"type": "add_leave", "payload": {
            "student": args["student"], "type": args.get("type") or "病假",
            "start_date": args.get("start_date") or today, "days": days,
            "reason": args.get("reason", ""),
            "attachment": bool(args.get("has_attachment"))}})
    elif intent == "add_todo" and args.get("title"):
        actions.append({"type": "add_todo", "payload": {
            "title": args["title"], "due": args.get("due") or "",
            "time": args.get("time") or "", "category": args.get("category") or "班级管理",
            "priority": args.get("priority") or "中"}})
    elif intent == "complete_todo" and args.get("keyword"):
        actions.append({"type": "complete_todo", "keyword": args["keyword"]})
    elif intent == "save_grades" and args.get("exam") and args.get("subject"):
        items = []
        for it in args.get("items") or []:
            if isinstance(it, dict):
                nm = it.get("student") or it.get("name") or ""
                sc = it.get("score")
            else:
                import re
                m = re.match(r"^(.+?)[,，\s]+(\d+(?:\.\d+)?)$", str(it).strip())
                nm, sc = (m.group(1), m.group(2)) if m else ("", None)
            if nm and sc is not None:
                items.append({"name": nm, "score": sc})
        if items:
            actions.append({"type": "save_grades", "payload": {
                "exam": args["exam"], "subject": args["subject"],
                "full": args.get("full") or 100, "date": args.get("date") or today,
                "items": items}})
    elif intent == "mark_attendance" and args.get("student"):
        actions.append({"type": "mark_attendance", "payload": {
            "student": args["student"], "date": args.get("date") or today,
            "mark": args.get("mark") or "旷课", "reason": args.get("reason", "")}})
    elif intent == "add_tag" and args.get("student") and args.get("tag"):
        actions.append({"type": "add_tag", "student": args["student"], "tag": args["tag"]})
    elif intent == "add_warning" and args.get("student"):
        actions.append({"type": "add_warning", "payload": {
            "student": args["student"], "kind": args.get("kind") or "其他",
            "level": args.get("level") or "黄", "desc": args.get("desc", "")}})
    elif intent == "update_student" and args.get("student") and args.get("field"):
        actions.append({"type": "update_student", "student": args["student"],
                        "field": args["field"], "value": args.get("value", "")})
    elif intent == "setup_semester" and args.get("name"):
        actions.append({"type": "setup_semester", "payload": {
            "name": args["name"], "start": args.get("start") or "",
            "weeks_n": args.get("weeks_n") or ""}})
    elif intent == "set_timetable" and args.get("entries"):
        ent = []
        for it in args["entries"]:
            if isinstance(it, dict):
                ent.append({"weekday": it.get("weekday", ""), "period": it.get("period", ""),
                            "course": it.get("course", ""), "odd": it.get("odd") or "all"})
            else:
                parts = [p.strip() for p in str(it).replace("，", ",").split(",") if p.strip()]
                if len(parts) >= 3:
                    ent.append({"weekday": parts[0], "period": parts[1],
                                "course": parts[2], "odd": "all"})
        if ent:
            actions.append({"type": "set_timetable", "entries": ent})
    elif intent == "gen_notice":
        actions.append({"type": "gen_notice", "payload": {
            "title": args.get("title") or "通知", "audience": args.get("audience") or "全体家长",
            "key_points": args.get("key_points") or ""}})

    return {"intent": intent, "reply": r.get("reply"), "questions": r.get("questions"),
            "actions": actions}


def draft_notice(cfg, title, audience, points):
    """让大模型写完整通知正文。失败时回退到模板拼装。"""
    msgs = [{"role": "user", "content":
             "请用中文起草一份班级通知。主题：%s；接收对象：%s；要点：%s。"
             "只输出通知正文，语气正式亲切，150字以内。" % (title, audience, points)}]
    r = chat(msgs, cfg)
    text = r.get("reply") or ""
    if r.get("intent") != "chat" or len(text) < 20:
        # 用模型直接文本
        text = _template_notice(title, audience, points)
    return text.strip()


def _template_notice(title, audience, points):
    return "【%s】\n%s：\n%s\n\n请知悉并配合，谢谢！" % (title, audience, points or "详见后续安排。")


# ================= 课表 AI 兜底理解 =================

def extract_timetable(config, grid_text):
    """规则解析失败时，把课表原样文本交给大模型理解，输出 entries。"""
    ai_cfg = config["ai"]
    prompt = ("这是班主任上传的学期课表（制表符分隔的表格文本）。请理解结构，提取每门课的 星期(周一~周日)、"
              "节次(如 1-2节/3-4节/5-6节/晚自习)、课程名、教师姓名(如有)、上课地点(如有)、"
              "周次区间(如 3-14周，无则空；不连续用逗号分段如 2-5,7-10)、单双周(odd/even/all)。\n"
              "严格只输出 JSON：{\"entries\":[{\"weekday\":\"周一\",\"period\":\"1-2节\",\"course\":\"高等数学\",\"teacher\":\"\",\"room\":\"\",\"weeks\":\"\",\"odd\":\"all\"}]}\n\n"
              + grid_text[:6000])
    payload = {"model": ai_cfg.get("model") or "deepseek-flash",
               "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.1, "response_format": {"type": "json_object"}}
    headers = {"Authorization": "Bearer " + ai_cfg.get("api_key", ""),
               "Content-Type": "application/json"}
    url = ai_cfg.get("base_url", "").rstrip("/") + "/chat/completions"
    r = httpx.post(url, json=payload, headers=headers, timeout=ai_cfg.get("timeout", 60))
    r.raise_for_status()
    out = json.loads(r.json()["choices"][0]["message"]["content"])
    return out.get("entries") or []
