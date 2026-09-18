# -*- coding: utf-8 -*-
"""把「班主任工作台」打包成单个 Windows exe。

用法：
    python build_exe.py

产出：dist\\班主任小助手.exe（单文件，双击直接弹窗口，目标机无需 Python）

注意：
--workpath / --distpath 刻意指向 %TEMP% 下的**新建空目录**，
PyInstaller 就不需要清理旧缓存，避免触发批量删除保护；
构建成功后再把 exe 复制回项目 dist/（覆盖写，不做删除）。
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "班主任小助手"

HIDDEN = [
    "pythonnet", "clr_loader",
    "uvicorn", "uvicorn.lifespan.on", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.websockets_impl",
    "anyio._backends._asyncio",
    "python_multipart", "multipart",
    "httpx", "openpyxl", "docx",
    "app.server.main", "app.server.data", "app.server.store",
    "app.server.features", "app.server.office", "app.server.ai",
]
EXCLUDE = ["tkinter", "PyQt5", "PySide2", "matplotlib", "numpy", "pandas",
           "IPython", "pytest", "PIL", "jupyter", "notebook", "scipy", "sklearn"]

log = []


def W(*a):
    log.append(" ".join(str(x) for x in a))


def main():
    stamp = time.strftime("%Y%m%d_%H%M%S")
    tmp_root = os.path.join(tempfile.gettempdir(), "bzk_build_" + stamp)
    work = os.path.join(tmp_root, "work")
    dist = os.path.join(tmp_root, "dist")
    spec = os.path.join(tmp_root, "spec")
    for d in (work, dist, spec):
        os.makedirs(d, exist_ok=True)
    W("workpath:", work)

    cmd = [sys.executable, "-m", "PyInstaller",
           "--noconsole", "--onefile", "--noconfirm",
           "--name", NAME,
           "--icon", os.path.join(ROOT, "app.ico"),
           "--add-data", os.path.join(ROOT, "app", "web") + os.pathsep + os.path.join("app", "web"),
           "--collect-all", "webview",
           "--distpath", dist, "--workpath", work, "--specpath", spec,
           ]
    for h in HIDDEN:
        cmd += ["--hidden-import", h]
    for e in EXCLUDE:
        cmd += ["--exclude-module", e]
    cmd += [os.path.join(ROOT, "desktop.py")]

    t0 = time.time()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=2400)
    W("耗时: %d 秒  返回码: %s" % (int(time.time() - t0), r.returncode))

    src = os.path.join(dist, NAME + ".exe")
    if r.returncode == 0 and os.path.exists(src):
        dst_dir = os.path.join(ROOT, "dist")
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, NAME + ".exe")
        shutil.copy2(src, dst)
        W("已生成: %s  %.2f MB" % (dst, os.path.getsize(dst) / 1024 / 1024))
    else:
        W("构建失败，未复制。")
        W("--- STDERR 末尾 80 行 ---")
        W("\n".join((r.stderr or "").splitlines()[-80:]))
        W("--- STDOUT 末尾 40 行 ---")
        W("\n".join((r.stdout or "").splitlines()[-40:]))

    with io.open(os.path.join(ROOT, "_build_log.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        log.append(traceback.format_exc())
        with io.open(os.path.join(ROOT, "_build_log.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(log) + "\n")
