import fcntl
import logging
import multiprocessing
import os
import pty
import signal
import struct
import sys
import termios
import threading
import time
import tty
from pathlib import Path
from types import SimpleNamespace

import setproctitle
from IPython.terminal.embed import InteractiveShellEmbed
from PySide6.QtCore import QObject, QUrl, QThread, Signal, Slot, Qt
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow
from traitlets.config import Config

from dottmi.ui.ui_elements import terminal_window, dottng_banner, dottng_notice


def start_shell():
    # 1. Create the embeddable shell instance
    # We pass user_ns=globals() so 'os' and other variables are shared
    ipshell = InteractiveShellEmbed(user_ns=globals())

    print("--- Entering IPython (Tab completion & Echo enabled) ---")

    # 2. This call handles the 'mainloop' correctly while
    # capturing the current local scope.
    ipshell(local_ns=locals())

    print("--- Returned to Script ---")
    print(f"OS module still works: {os.name}")


class TerminalBridge(QObject):
    def __init__(self):
        super().__init__()
        self._pipe_writer: multiprocessing.Pipe | None = None

    @Slot(str)
    def send_to_pty(self, data):
        if self._pipe_writer:
            self._pipe_writer.send(data)

    @Slot()
    def emit_resize_signal(self):
        # Emit signal.SIGWINCH signal for apps running in iPython (e.g., Textual, vim, ...)
        os.killpg(os.getpgrp(), signal.SIGWINCH)

    def set_pipe_writer(self, pipe):
        self._pipe_writer = pipe


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.browser = QWebEngineView()
        self.browser.setFocusPolicy(Qt.StrongFocus)
        self.browser.setFocus()
        self.conn = None

        self.init_done = False

        self.channel = QWebChannel()
        self.bridge = TerminalBridge()
        self.channel.registerObject("pyBridge", self.bridge)
        self.browser.page().setWebChannel(self.channel)
        current_dir = Path(__file__).resolve().parent
        base_url = QUrl.fromLocalFile(str(current_dir) + os.path.sep)
        self.browser.setHtml(terminal_window, baseUrl=base_url)
        self.setCentralWidget(self.browser)
        self.browser.loadFinished.connect(self._init_done)

    def _init_done(self):
        self.init_done = True
        self.write_to_terminal(dottng_banner, "37")
        self.write_to_terminal(dottng_notice, "33")
        self.write_to_terminal("\n")

    def write_to_terminal(self, text, color_code="0"):
        # ANSI escape sequence for color
        # Note the double backslash for the escape character in Python strings
        formatted_text = f"\x1b[{color_code}m{text}\x1b[0m"

        # Repr handles escaping for the JavaScript string literal
        js_code = f"window.term.write({repr(formatted_text)})"
        self.browser.page().runJavaScript(js_code)

    def update_log(self, message):
        js_code = f"window.term.write({repr(message)})"
        self.browser.page().runJavaScript(js_code)


# --- Qt Worker ---
class PipeWorker(QObject):
    """Handles the blocking pipe.recv() in a background thread."""
    data_received = Signal(str)

    def __init__(self, pipe_end):
        super().__init__()
        self.pipe_end = pipe_end
        self._running = True

    @Slot()
    def start_listening(self):
        while self._running:

            try:
                # This call blocks the background thread, NOT the GUI
                if self.pipe_end.poll(0.01):  # Check with timeout to stay responsive to stop
                    data = self.pipe_end.recv().decode('utf-8', errors='replace')
                    # data = pipe_reader.readline()
                    self.data_received.emit(f"{data}")

            except EOFError:
                break

    def stop(self):
        self._running = False


def start_gui_in_thread(conn):
    os.environ.pop("QT_STYLE_OVERRIDE", None)
    os.environ["QT_LOGGING_RULES"] = "qt.qpa.services=false"
    app = QApplication(sys.argv)
    app_name: str = "DOTT.NG Shell"
    app.setApplicationName(app_name)
    app.setDesktopFileName(app_name)
    setproctitle.setproctitle(app_name)
    window = MainWindow()
    window.setWindowTitle("DOTT.NG - Interactive Shell")
    window.resize(1900, 1040)
    window.show()
    window.conn = conn

    # 2. Setup Thread and Worker
    thread = QThread()
    worker = PipeWorker(conn)

    # pipe_writer = os.fdopen(os.dup(conn.fileno()), 'w', buffering=1)
    # window.bridge.set_pipe_writer(pipe_writer)
    window.bridge.set_pipe_writer(conn)

    thread.started.connect(worker.start_listening)
    worker.data_received.connect(window.update_log)
    worker.moveToThread(thread)
    thread.start()
    ret_val = app.exec()
    print(f"QApp exec loop finished ({ret_val})")
    conn.send("exit\n".encode('utf-8'))
    sys.exit(ret_val)


# 1. Thread to read from Pipe (from xterm.js) and write to PTY master
def pipe_to_pty(pipe_conn: multiprocessing.Pipe, master_fd):
    while True:
        try:

            data = pipe_conn.recv()  # Expecting bytes or strings
            if data:
                data_bytes: bytes = data.encode('utf-8') if isinstance(data, str) else data
                data_str: str = data if isinstance(data, str) else data.decode('utf-8')
                if "DOTTNG_CTRL_RESIZE" in data_str:
                    rows = int(data_str.split(" ")[1])
                    cols = int(data_str.split(" ")[2])
                    set_size(rows, cols)
                    continue

                os.write(master_fd, data_bytes)
        except EOFError:
            break


# 2. Thread to read from PTY master (IPython output) and send to Pipe
def pty_to_pipe(pipe_conn: multiprocessing.Pipe, master_fd):
    while True:
        try:
            output = os.read(master_fd, 1024)
            if output:
                pipe_conn.send(output)
        except OSError:
            break
        except NameError:
            print("NameError Exception")
            break
        except Exception:
            print("General Exception")
            break


master_fd = None


def set_size(rows, cols):
    # Standard fallback if you don't have frontend data yet
    # but ideally, get these numbers from your xterm.js fit addon
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)



def dott_shell(**kwargs):
    global master_fd
    logging.getLogger('asyncio').setLevel(logging.WARNING)

    ctx = SimpleNamespace(**kwargs)

    multiprocessing.freeze_support()
    #    multiprocessing.set_start_method('spawn', force=True)
    parent_conn, child_conn = multiprocessing.Pipe(duplex=True)
    proc = multiprocessing.Process(target=start_gui_in_thread, daemon=True, args=(child_conn,))
    proc.start()
    time.sleep(2)

    master_fd, slave_fd = pty.openpty()

    tty.setcbreak(slave_fd)

    # 1. SET THE TTY ATTRIBUTES MANUALLY
    attrs = termios.tcgetattr(slave_fd)

    # INPUT: Disable ICANON (gives us arrows/tabs immediately)
    # INPUT: Disable ECHO (IPython will handle the echo itself)
    attrs[3] &= ~(termios.ICANON | termios.ECHO)

    # OUTPUT: Enable OPOST and ONLCR (fixes the "no output/staircase" issue)
    attrs[1] |= (termios.OPOST | termios.ONLCR)
    termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)

    # Backup originals
    old_stdin = os.dup(sys.stdin.fileno())
    old_stdout = os.dup(sys.stdout.fileno())

    # redirect stdio to slave process
    os.dup2(slave_fd, sys.stdin.fileno())
    os.dup2(slave_fd, sys.stdout.fileno())
    os.dup2(slave_fd, sys.stderr.fileno())

    # start relay threads
    threading.Thread(target=pipe_to_pty, args=(parent_conn, master_fd), daemon=True).start()
    threading.Thread(target=pty_to_pipe, args=(parent_conn, master_fd), daemon=True).start()

    # iPython configuration
    cfg = Config()
    cfg.TerminalInteractiveShell.simple_prompt = False
    cfg.TerminalInteractiveShell.term_title = False
    cfg.TerminalInteractiveShell.auto_match=True
    cfg.TerminalInteractiveShell.highlight_matching_brackets = True
    cfg.InteractiveShellEmbed.banner1 = ""
    cfg.InteractiveShellEmbed.banner2 = ""
    cfg.TerminalInteractiveShell.autosuggestions_provider = None
    cfg.TerminalIPythonApp.ignore_old_config = True

    try:
        os.environ["TERM"] = "xterm-256color"
        shell = InteractiveShellEmbed(config=cfg)
        # disable iPython tips
        shell.enable_tip = False
        try:
            shell()
        except SystemExit:
            pass
    except Exception as ex:
        pass
    finally:
        # Always restore originals to avoid breaking your script
        os.dup2(old_stdin, sys.stdin.fileno())
        os.dup2(old_stdout, sys.stdout.fileno())
        os.dup2(old_stdout, sys.stderr.fileno())

        proc.kill()
        proc.join()

