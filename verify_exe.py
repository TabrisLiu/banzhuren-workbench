# -*- coding: utf-8 -*-
"""验证 dist/班主任小助手.exe：窗口标题 + 服务 + 出厂状态。"""
import ctypes
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import traceback
import urllib.request

ROOT = r"C:\AI Agent生成文件\work buddy 班主任工作台"
EXE = os.path.join(ROOT, "dist", "班主任小助手.exe")
L = []
proc = None


def W(*a):
    L.append(" ".join(str(x) for x in a))


def titles_of(pid=None):
    """枚举可见窗口标题；pid 为 None 时不限进程（webview 窗口常在子进程）。"""
    out = []
    EnumWindows = ctypes.windll.user32.EnumWindows
    GetWindowTextW = ctypes.windll.user32.GetWindowTextW
    GetWindowTextLengthW = ctypes.windll.user32.GetWindowTextLengthW
    IsWindowVisible = ctypes.windll.user32.IsWindowVisible
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int),
                                     ctypes.POINTER(ctypes.c_int))

    def cb(hwnd, _):
        if not IsWindowVisible(hwnd):
            return True
        if pid is not None:
            pid_out = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_out))
            if pid_out.value != pid:
                return True
        n = GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            GetWindowTextW(hwnd, buf, n + 1)
            out.append(buf.value)
        return True

    EnumWindows(WNDENUMPROC(cb), 0)
    return out


try:
    if not os.path.exists(EXE):
        raise RuntimeError("找不到 " + EXE)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    TEST = os.path.join(tempfile.gettempdir(), "bzk_verify_" + stamp, "app")
    os.makedirs(TEST, exist_ok=True)
    dst = os.path.join(TEST, "班主任小助手.exe")
    shutil.copy2(EXE, dst)
    W("exe: %.2f MB" % (os.path.getsize(dst) / 1024 / 1024))

    proc = subprocess.Popen([dst], cwd=TEST)
    pid = proc.pid
    W("PID =", pid)

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    ok, port = False, None
    end = time.time() + 90
    while time.time() < end:
        if proc.poll() is not None:
            W("!! 进程退出，返回码 =", proc.returncode)
            break
        for p in range(8790, 8800):
            try:
                with opener.open("http://127.0.0.1:%d/api/config" % p, timeout=1) as r:
                    if r.status == 200:
                        ok, port = True, p
                        break
            except Exception:
                pass
        if ok:
            break
        time.sleep(1)
    W("服务:", "OK" if ok else "FAIL", "(端口 %s)" % port)

    time.sleep(3)
    ts_pid = titles_of(pid)
    W("本进程窗口:", ts_pid if ts_pid else "（无）")
    all_t = titles_of(None)
    hit = [t for t in all_t if "班主任" in t]
    W("全局含「班主任」的窗口:", hit if hit else "（无）")
    W("标题含「班主任小助手」:", any("班主任小助手" in t for t in hit))
    W("标题含「班主任工作台」:", any("班主任工作台" in t for t in hit))

    if ok:
        with opener.open("http://127.0.0.1:%d/api/config" % port, timeout=5) as r:
            cfg = json.loads(r.read().decode("utf-8"))
        W("initialized =", cfg.get("initialized"),
          "| 班级为空 =", not (cfg.get("class") or {}).get("name"),
          "| api_key 为空 =", not (cfg.get("ai") or {}).get("api_key"))
        with opener.open("http://127.0.0.1:%d/" % port, timeout=5) as r:
            html = r.read().decode("utf-8", "ignore")
        W("首页 %d 字节，含向导 = %s" % (len(html), 'id="wizard"' in html))
    W("启动错误日志:", "有！" if os.path.exists(os.path.join(TEST, "_启动错误.log")) else "无")
except Exception:
    W(traceback.format_exc())
finally:
    if proc and proc.poll() is None:
        proc.kill()
        W("已结束进程")
    with io.open(os.path.join(ROOT, "_verify.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
print("done")
