"""
FishyBox 启动器：后台启动 FastAPI，优先 pywebview 独立窗口，失败则回退系统浏览器。
含 Windows 单实例锁（命名 Mutex）+ 关闭窗口时优雅退出。
含日志输出（fishybox.log，与 exe 同目录），用于排查。

打包命令（在项目根目录执行）：
    pyinstaller FishyBox.spec
"""
import os
import socket
import subprocess
import sys
import threading
import time

import uvicorn

# 打包成 --noconsole（无黑窗口）时 stdout/stderr 为 None，先重定向到空设备
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

if getattr(sys, "frozen", False):
    LOG_FILE = os.path.join(os.path.dirname(sys.executable), "fishybox.log")
else:
    LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fishybox.log")


def _log(msg: str) -> None:
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%H:%M:%S] ") + msg + "\n")
    except Exception:
        pass


_log("=== launcher starting ===")

from app import app  # noqa: E402

PORT = 8000
URL = f"http://127.0.0.1:{PORT}"


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_server() -> None:
    def _run() -> None:
        try:
            uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
        except Exception as e:
            _log("server thread error: " + repr(e))

    threading.Thread(target=_run, daemon=True).start()


def wait_for_server(timeout: float = 12.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_in_use(PORT):
            return True
        time.sleep(0.2)
    return False


def acquire_single_instance():
    import ctypes

    kernel32 = ctypes.windll.kernel32
    name = "Local\\FishyBox_SingleInstance"
    handle = kernel32.CreateMutexW(None, False, name)
    already = kernel32.GetLastError() == 183
    return handle, already


def show_message(text: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, "FishyBox", 0x40)
    except Exception:
        pass


def _open_browser(url: str) -> bool:
    """依次尝试多种方式打开默认浏览器，返回是否成功。"""
    # 1. Edge/Chrome App 模式（独立窗口）+ 独立配置目录（避免和现有浏览器冲突）
    #    配置目录放 %LOCALAPPDATA%，不放在程序目录（避免锁住程序文件夹，影响重新打包）
    profile = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "FishyBox", "edge_profile"
    )
    for exe in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ):
        if os.path.exists(exe):
            try:
                subprocess.Popen(
                    [exe, "--app=" + url, "--user-data-dir=" + profile],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
                _log("browser: app mode OK -> " + exe)
                return True
            except Exception as e:
                _log("browser: app mode failed -> " + repr(e))
    # 2. cmd /c start（隐藏控制台窗口）
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        _log("browser: cmd start OK")
        return True
    except Exception as e:
        _log("browser: cmd start failed -> " + repr(e))
    # 3. os.startfile（ShellExecute）
    try:
        os.startfile(url)
        _log("browser: os.startfile OK")
        return True
    except Exception as e:
        _log("browser: os.startfile failed -> " + repr(e))
    # 4. webbrowser
    try:
        import webbrowser

        if webbrowser.open(url):
            _log("browser: webbrowser OK")
            return True
        _log("browser: webbrowser returned False")
    except Exception as e:
        _log("browser: webbrowser failed -> " + repr(e))
    _log("browser: ALL methods failed")
    return False


def _try_pywebview():
    """尝试加载 pywebview 及其 Windows 后端；失败返回 None。"""
    try:
        import webview
        import webview.platforms.winforms  # noqa: F401  触发 pythonnet
        _log("pywebview: backend loaded OK")
        return webview
    except Exception as e:
        _log("pywebview: backend failed -> " + repr(e))
        return None


def main() -> None:
    _log("main: start")
    _handle, already = acquire_single_instance()
    if already:
        _log("main: another instance, exit")
        show_message("FishyBox 已在运行，请勿重复打开。")
        return

    if not port_in_use(PORT):
        _log("main: starting server")
        start_server()
        if not wait_for_server():
            _log("main: server failed to start")
            show_message("服务启动失败，请重试。")
            return
        time.sleep(1.0)  # 等服务完全就绪
        _log("main: server up")
    else:
        _log("main: port already in use")

    wv = _try_pywebview()
    if wv is not None:
        try:
            window = wv.create_window(
                "FishyBox", URL, width=920, height=720, min_size=(560, 480)
            )
            _log("main: webview window created, starting GUI loop")
            wv.start()
            _log("main: webview closed, exit")
            os._exit(0)
        except Exception as e:
            _log("main: webview start failed -> " + repr(e))

    _log("main: falling back to browser")
    _open_browser(URL)
    # 不弹窗：由同目录的「启动FishyBox.bat」负责打开浏览器（更可靠）
    # 保持后台服务运行；用户用页面里的「退出程序」按钮结束进程
    _log("main: entering keep-alive loop")
    # 看门狗：页面关闭后（心跳停止 90 秒）自动退出，避免进程残留
    try:
        while True:
            time.sleep(15)
            idle = time.time() - app.state.last_heartbeat
            if idle > 90:
                _log(f"watchdog: no heartbeat for {int(idle)}s, exiting")
                os._exit(0)
    except BaseException as e:
        _log("main: keep-alive loop exited -> " + repr(e))
    _log("main: exiting")
    os._exit(0)


if __name__ == "__main__":
    main()
