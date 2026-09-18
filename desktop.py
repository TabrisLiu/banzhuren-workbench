# -*- coding: utf-8 -*-
"""班主任工作台 · Windows 桌面启动器（PyInstaller 打包入口）。

双击 exe 后：
1. 自动挑一个空闲端口（默认从 8790 起，被占用就往后找）
2. 后台线程起 uvicorn 服务（只监听 127.0.0.1，数据不出本机）
3. 弹出一个独立窗口（WebView2 渲染），没有浏览器地址栏和控制台黑框
4. 关闭窗口即退出整个程序

打包命令见 build_exe.bat / build_exe.spec。
"""
import os
import socket
import sys
import threading
import time
import traceback

APP_NAME = "班主任小助手"
HOST = "127.0.0.1"
PORT_START = 8790
PORT_TRIES = 30


def ensure_streams():
    """--noconsole 打包后 sys.stdout / sys.stderr 是 None。

    uvicorn 的默认日志格式化器会调 sys.stderr.isatty()，无控制台时直接抛
    AttributeError 导致整个程序起不来。这里给它们接上空设备占位。
    """
    if sys.stdout is None or sys.stderr is None:
        devnull = open(os.devnull, "w", encoding="utf-8")
        if sys.stdout is None:
            sys.stdout = devnull
        if sys.stderr is None:
            sys.stderr = devnull


def pick_port(start=PORT_START, tries=PORT_TRIES):
    """挑一个空闲端口：被占用就顺延，避免多实例或别的软件抢占时启动失败。"""
    for p in range(start, start + tries):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((HOST, p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    return None


def wait_port(port, timeout=20.0):
    """等后端真正 listening 再开窗口，避免用户看到白屏。"""
    end = time.time() + timeout
    while time.time() < end:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            if s.connect_ex((HOST, port)) == 0:
                return True
        except OSError:
            pass
        finally:
            s.close()
        time.sleep(0.2)
    return False


def main():
    ensure_streams()
    port = pick_port()
    if port is None:
        raise RuntimeError("找不到可用端口（%d ~ %d 均被占用）" %
                           (PORT_START, PORT_START + PORT_TRIES - 1))

    import uvicorn
    from app.server.main import app as fastapi_app

    # log_config=None：不套 uvicorn 默认的 dictConfig 日志（其格式化器依赖 tty）
    cfg = uvicorn.Config(fastapi_app, host=HOST, port=port,
                         log_level="warning", access_log=False,
                         log_config=None)
    server = uvicorn.Server(cfg)
    threading.Thread(target=server.run, daemon=True).start()

    if not wait_port(port):
        raise RuntimeError("本地服务启动超时")

    if os.environ.get("BZK_NO_WINDOW"):
        # 自检模式：只起服务、不弹窗口（无控制台，用标记文件回报端口）
        try:
            with open(os.path.join(os.path.dirname(sys.executable), "_ready.txt"), "w") as f:
                f.write("READY %d\n" % port)
        except Exception:
            pass
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.should_exit = True
        return

    import webview
    webview.create_window(
        APP_NAME,
        "http://%s:%d" % (HOST, port),
        width=1440, height=900, min_size=(1024, 680),
        text_select=True,
    )
    webview.start()          # 阻塞，窗口关闭后返回
    server.should_exit = True   # 收尾：让后台服务线程退出
    time.sleep(0.3)


if __name__ == "__main__":
    # 打包后 sys.path 可能没有脚本所在目录，补上以便 import app.server.main
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        main()
    except Exception as e:
        # 无控制台，出错必须能看到原因：既弹窗，也在 exe 同级留下日志
        msg = "%s\n\n%s" % (APP_NAME + " 启动失败", e)
        try:
            log_dir = os.path.dirname(sys.executable) if getattr(
                sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(log_dir, "_启动错误.log"), "w", encoding="utf-8") as f:
                f.write(msg + "\n\n" + traceback.format_exc())
        except Exception:
            pass
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, APP_NAME, 0x10)
        except Exception:
            pass
        sys.exit(1)
