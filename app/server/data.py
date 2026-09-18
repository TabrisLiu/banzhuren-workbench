# -*- coding: utf-8 -*-
"""数据层：本地 JSON 文件数据库。
- 所有数据存于 data/ 目录，按模块分文件；写入前自动快照到 files/backups/。
- 每次写操作记入 ops_log.json（支持撤销），记录含 before/after 键值差异。
- 全局主键：student_id（学号）。所有记录都带 class_id，为将来多班预留。
"""
import json
import os
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime


def _resolve_base():
    """程序运行基准目录（config.json / data / files 的父目录）。
    - PyInstaller 打包后：__file__ 位于临时解压目录，必须改用 exe 所在目录，
      否则数据会写进 %TEMP%，关掉程序即丢失。
    - 开发环境：项目根目录（与原来一致）。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


BASE = _resolve_base()
CONFIG_PATH = os.path.join(BASE, "config.json")

_LOCK = threading.RLock()

# 每个数据文件的内存缓存：name -> {json:..., updated_at:...}
_CACHE = {}

# ---- 动态存储位置：config.json 里 storage.data_dir 为空则用程序目录 ----
_STORAGE = {"data_dir": os.path.join(BASE, "data"),
            "files_dir": os.path.join(BASE, "files")}


def refresh_storage():
    """从 config.json 读取自定义数据目录（存储键），同步内部路径并清缓存。"""
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    d = (cfg.get("storage") or {}).get("data_dir") or ""
    if d and os.path.isdir(d):
        _STORAGE["data_dir"] = os.path.abspath(d)
        _STORAGE["files_dir"] = os.path.abspath(os.path.join(d, "files"))
    else:
        _STORAGE["data_dir"] = os.path.join(BASE, "data")
        _STORAGE["files_dir"] = os.path.join(BASE, "files")
    _CACHE.clear()
    ensure_dirs()


def data_dir():
    return _STORAGE["data_dir"]


def files_dir():
    return _STORAGE["files_dir"]


def __getattr__(name):
    """兼容旧引用：data.DATA_DIR / FILES_DIR / BACKUP_DIR / EXCEL_DIR / WORD_DIR / PHOTO_DIR"""
    mapping = {
        "DATA_DIR": lambda: data_dir(),
        "FILES_DIR": lambda: files_dir(),
        "BACKUP_DIR": lambda: os.path.join(files_dir(), "backups"),
        "EXCEL_DIR": lambda: os.path.join(files_dir(), "excel"),
        "WORD_DIR": lambda: os.path.join(files_dir(), "word"),
        "PHOTO_DIR": lambda: os.path.join(files_dir(), "photos"),
    }
    if name in mapping:
        return mapping[name]()
    raise AttributeError("module 'data' has no attribute %r" % name)


def _data_path(name):
    return os.path.join(data_dir(), name + ".json")


def ensure_dirs():
    for d in (data_dir(), files_dir(), os.path.join(files_dir(), "backups"),
              os.path.join(files_dir(), "excel"), os.path.join(files_dir(), "word"),
              os.path.join(files_dir(), "photos")):
        os.makedirs(d, exist_ok=True)


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


# ---------- 配置 ----------

DEFAULT_CONFIG = {
    "initialized": False,
    "storage": {"data_dir": ""},
    "ai": {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "api_key": "",
        "timeout": 60,
    },
    "class": {
        "class_id": "default",
        "name": "",
        "major": "",
        "grade": "",
        "head_teacher": "",
        "phone": "",
        "size_expect": 40,
    },
    "semester": {
        "name": "",
        "start_date": "",
        "total_weeks": 20,
        "holidays": [],
    },
    "term": 0,
    "settings": {
        "warn_fail_courses": 2,
        "warn_score_drop": 10,
        "leave_notify_parent": True,
        "privacy_warn": False,
    },
}


def load_config():
    with _LOCK:
        cfg = None
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                cfg = None
        cfg = cfg or {}
        merged = json.loads(json.dumps(DEFAULT_CONFIG))
        _deep_merge(merged, cfg)
        return merged


def save_config(cfg):
    with _LOCK:
        if os.path.exists(CONFIG_PATH):
            try:
                d = os.path.join(files_dir(), "backups", time.strftime("%Y%m%d"))
                os.makedirs(d, exist_ok=True)
                shutil.copy2(CONFIG_PATH, os.path.join(
                    d, time.strftime("%Y%m%d_%H%M%S") + "_config.json"))
            except Exception:
                pass
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    refresh_storage()
    return cfg


def snapshot_config():
    """当前 config 的深拷贝（供撤销记录 before）。"""
    with _LOCK:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None


def restore_config(cfg):
    """撤销时整份恢复 config（不写日志防递归）。"""
    with _LOCK:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    refresh_storage()


def log_config(before, source="manual"):
    """记录一次 config 变更（before 快照），供撤销。"""
    with _LOCK:
        _log("__config__", "set", "obj", before, {"keys": []}, source, True)


def _deep_merge(dst, src):
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v


# ---------- 通用记录库（list 型） ----------

def load(name):
    """读取一个数据文件，返回 dict 包裹的记录集合 {class_id: [records]}。"""
    with _LOCK:
        path = _data_path(name)
        if name in _CACHE and os.path.exists(path) and \
                _CACHE[name]["mtime"] == os.path.getmtime(path):
            return _CACHE[name]["json"]
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        _CACHE[name] = {"json": data, "mtime": os.path.getmtime(path) if os.path.exists(path) else 0}
        return data


def records(name, class_id=None):
    """返回记录列表。class_id=None 时返回全部班级（首页汇总可用）。"""
    data = load(name)
    if class_id:
        return [r for r in data.get(class_id, []) if not r.get("_deleted")]
    out = []
    for lst in data.values():
        out.extend([r for r in lst if not r.get("_deleted")])
    return out


def insert(name, rec, class_id, source="manual", undoable=True):
    """插入一条记录，返回 rec。自动补 uid/时间戳/来源，并写快照与操作日志。"""
    with _LOCK:
        data = load(name)
        lst = data.setdefault(class_id, [])
        rec.setdefault("uid", uuid.uuid4().hex[:10])
        rec.setdefault("class_id", class_id)
        rec["created_at"] = now_str()
        rec["updated_at"] = rec["created_at"]
        rec["source"] = source
        _snapshot(name)
        lst.append(rec)
        _write(name, data)
        _log(name, "insert", rec["uid"], None, rec, source, undoable)
        return rec


def update(name, uid, patch, class_id, source="manual", undoable=True):
    """按 uid 更新一条记录，patch 为字段字典。返回更新后的记录或 None。"""
    with _LOCK:
        data = load(name)
        for r in data.get(class_id, []):
            if r.get("uid") == uid:
                before = json.loads(json.dumps(r))
                _apply_patch(r, patch)
                r["updated_at"] = now_str()
                _snapshot(name)
                _write(name, data)
                _log(name, "update", uid, before, r, source, undoable)
                return r
        return None


def remove(name, uid, class_id, source="manual", hard=False):
    """删除（默认软删除，保留 _deleted 标记以便撤销）。"""
    with _LOCK:
        data = load(name)
        lst = data.get(class_id, [])
        for r in lst:
            if r.get("uid") == uid:
                before = json.loads(json.dumps(r))
                if hard:
                    lst.remove(r)
                else:
                    r["_deleted"] = True
                    r["updated_at"] = now_str()
                _snapshot(name)
                _write(name, data)
                _log(name, "delete", uid, before, r, source, True)
                return True
        return False


def _apply_patch(r, patch):
    for k, v in patch.items():
        if k in ("uid", "class_id", "created_at"):
            continue
        r[k] = v


# ---------- 配置型单对象 ----------

def get_obj(name, default=None):
    data = load(name)
    return data.get("obj", default)


def set_obj(name, obj, source="manual"):
    with _LOCK:
        data = load(name)
        _snapshot(name)
        data["obj"] = obj
        _write(name, data)
        _log(name, "set_obj", "obj", None, {"keys": list(obj.keys())}, source, False)


# ---------- 批量（导入用） ----------

def bulk_insert(name, recs, class_id, source="import", undoable=False):
    """批量插入；返回 (插入数, 按 key 去重跳过的 uid 列表)。
    注意：批量导入不产生可撤销的单条日志（撤销请用 files/backups 快照恢复）。"""
    with _LOCK:
        data = load(name)
        lst = data.setdefault(class_id, [])
        added, skipped = 0, []
        _snapshot(name)
        for rec in recs:
            key_field = rec.pop("_dedup_field", None)
            if key_field and any(r.get(key_field) == rec.get(key_field) for r in lst):
                old = [r for r in lst if r.get(key_field) == rec.get(key_field)][0]
                skipped.append(old["uid"])
                continue
            rec.setdefault("uid", uuid.uuid4().hex[:10])
            rec.setdefault("class_id", class_id)
            rec["created_at"] = now_str()
            rec["updated_at"] = rec["created_at"]
            rec["source"] = source
            lst.append(rec)
            added += 1
        _write(name, data)
        _log(name, "bulk_insert", "-", None, {"count": added, "skipped": skipped},
             source, undoable)
        return added, skipped


# ---------- 落盘 / 快照 / 日志 ----------

def _write(name, data):
    path = _data_path(name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    _CACHE[name] = {"json": data, "mtime": os.path.getmtime(path)}


def _snapshot(name):
    path = _data_path(name)
    if not os.path.exists(path):
        return
    stamp = time.strftime("%Y%m%d_%H%M%S")
    d = os.path.join(files_dir(), "backups", time.strftime("%Y%m%d"))
    os.makedirs(d, exist_ok=True)
    try:
        shutil.copy2(path, os.path.join(d, "%s_%s.json" % (stamp, name)))
    except Exception:
        pass


def _log(name, action, uid, before, after, source, undoable=True):
    path = _data_path("ops_log")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = []
    data.append({
        "ts": now_str(), "file": name, "action": action, "uid": uid,
        "before": before, "after": after if action in ("insert", "delete") else None,
        "source": source, "undoable": undoable,
    })
    data = data[-200:]
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def last_op():
    path = _data_path("ops_log")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data[-1] if data else None
    except Exception:
        return None


def undo_last():
    """撤销最近一次 undoable 的写操作（insert=删除该条 / update=恢复 before / delete=恢复记录）。"""
    with _LOCK:
        path = _data_path("ops_log")
        try:
            with open(path, "r", encoding="utf-8") as f:
                ops = json.load(f)
        except Exception:
            return False, "无操作日志"
        idx = None
        for i in range(len(ops) - 1, -1, -1):
            if ops[i].get("undoable"):
                idx = i
                break
        if idx is None:
            return False, "没有可撤销的操作"
        op = ops[idx]
        name, action, uid = op["file"], op["action"], op["uid"]
        if action == "bulk_insert":
            # 批量导入无法按单条回退，且日志里没有完整的 before 快照——
            # 明确告知不可撤，避免"假装撤销成功"误导（数据可从 files/backups 手动恢复）
            return False, "批量导入不支持一键撤销（已自动快照，可到 files/backups 恢复）"
        if name == "__config__":
            ops.pop(idx)
            if op.get("before"):
                restore_config(op["before"])
            op["action"] = "undo"
            op["undoable"] = False
            ops.append(op)
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(ops, f, ensure_ascii=False, indent=1)
            os.replace(path + ".tmp", path)
            return True, "已恢复设置(config)"
        data = load(name)
        cid = op.get("class_id") or ""
        if not cid:
            for k, lst in data.items():
                if any(r.get("uid") == uid for r in lst):
                    cid = k
                    break
        if not cid:
            return False, "找不到该记录，无法撤销（可能已被手动清理）"
        ops.pop(idx)
        if action == "insert":
            data[cid] = [r for r in data.get(cid, []) if r.get("uid") != uid]
        elif action == "update":
            for r in data.get(cid, []):
                if r.get("uid") == uid:
                    r.clear()
                    r.update(op["before"])
        elif action == "delete":
            for r in data.get(cid, []):
                if r.get("uid") == uid:
                    r.pop("_deleted", None)
        _snapshot(name)
        _write(name, data)
        op["action"] = "undo"
        op["undoable"] = False
        ops.append(op)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(ops, f, ensure_ascii=False, indent=1)
        os.replace(path + ".tmp", path)
        return True, "已撤销 %s" % action
