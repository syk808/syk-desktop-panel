"""SYK 小组件合集: 统一查看/启动/关闭桌面小窗口, 以及开机自启开关。外观与 TokPay 一致。"""
import ctypes, json, os, shutil, subprocess, sys, threading, tkinter as tk
import psutil
from PIL import Image, ImageDraw, ImageTk

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "hub_config.json")
PYW = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
HOME = os.path.expanduser("~")
STARTUP = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
DISABLED = os.path.join(STARTUP, "Disabled")

# match: 进程命令行里要包含的文件名; start: 启动命令; lnk: 这个组件在「启动」文件夹里可能用的文件名(第一个是由本面板创建的)
WIDGETS = [
    {"key": "panel", "name": "SYK 面板", "desc": "本窗口 · 回本 / 时间 / 管理 合在一起", "match": "panel.py",
     "start": [PYW, os.path.join(HERE, "panel.py")], "cwd": HERE,
     "lnk": ["SYK-Panel.vbs"]},
    {"key": "stonk", "name": "Stonk 监控", "desc": "后台程序 · 新配对推送到 TG", "match": "stonk_monitor.py",
     "start": [PYW, os.path.join(HOME, r"stonk-monitor\stonk_monitor.py")], "cwd": os.path.join(HOME, "stonk-monitor"),
     "lnk": ["SYK-Stonk.vbs", "Stonk Monitor.lnk"]},
]

BG, CARD, FG, MUT, TRACK, EDGE = "#161615", "#222220", "#f3f2ee", "#8f8c84", "#34332f", "#2e2d2a"
GREEN, ACC = "#2fa36b", "#6f9bff"
FONT, F = "Segoe UI Variable Text", "Microsoft YaHei UI"


def load_cfg():
    try:
        c = json.load(open(CFG, encoding="utf-8"))
    except Exception:
        c = {}
    for k, v in (("pinned", False), ("x", None), ("y", None)):
        c.setdefault(k, v)
    return c


def scan():
    """一次扫描所有组件: 先按进程名筛出 python, 再读命令行(读全部进程的命令行很慢)。"""
    found = {w["key"]: [] for w in WIDGETS}
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() not in ("pythonw.exe", "python.exe"):
                continue
            cmd = " ".join(p.cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        for w in WIDGETS:
            if w["match"] in cmd:
                found[w["key"]].append(p)
    return found


def procs(w):
    return scan()[w["key"]]


def autostart_on(w):
    return any(os.path.exists(os.path.join(STARTUP, n)) for n in w["lnk"])


def set_autostart(w, on):
    os.makedirs(DISABLED, exist_ok=True)
    if on:
        for n in w["lnk"]:                      # 之前被关掉的先挪回来
            src = os.path.join(DISABLED, n)
            if os.path.exists(src):
                shutil.move(src, os.path.join(STARTUP, n))
                return
        cmd = " ".join(f'""{a}""' for a in w["start"])
        vbs = ('Set sh = CreateObject("WScript.Shell")\r\n'
               f'sh.CurrentDirectory = "{w["cwd"]}"\r\n'
               f'sh.Run "{cmd}", 0, False\r\n')
        open(os.path.join(STARTUP, w["lnk"][0]), "w", encoding="mbcs").write(vbs)
    else:
        for n in w["lnk"]:                      # 关 = 挪进 Disabled, 不删除
            src = os.path.join(STARTUP, n)
            if os.path.exists(src):
                dst = os.path.join(DISABLED, n)
                if os.path.exists(dst):
                    os.remove(dst)
                shutil.move(src, dst)


def start(w):
    if not procs(w):
        subprocess.Popen(w["start"], cwd=w["cwd"], creationflags=0x00000008 | 0x08000000, close_fds=True)


def stop(w):
    for p in procs(w):
        try:
            p.terminate()
        except psutil.Error:
            pass


class App:
    ROW, TOP = 62, 5        # 和时区列表一样: 一张卡片里分行, 行间细线

    def __init__(self, master=None, on_resize=None, width=400):
        self.embedded, self.on_resize = master is not None, on_resize
        self.cfg = load_cfg()
        zoom = float(os.environ.get("SYK_ZOOM") or 1.0)
        if self.embedded:
            r = self.root = master.winfo_toplevel()
            host = master
        else:
            r = self.root = tk.Tk()
            host = r
            r.title("SYK 小组件")
            r.configure(bg=BG)
            r.resizable(False, False)
            r.overrideredirect(True)
        self.z = zoom
        self.S = S = max(1.0, r.winfo_fpixels("1i") / 96) * zoom
        self.W = w = int(width * S)
        self.pad = int(14 * S)
        self.cw = w - 2 * self.pad
        if not self.embedded:
            x = self.cfg["x"] if self.cfg["x"] is not None else (r.winfo_screenwidth() - w) // 2
            y = self.cfg["y"] if self.cfg["y"] is not None else int(120 * S)
            r.geometry(f"{w}x{int(300 * S)}+{x}+{y}")
            r.attributes("-topmost", bool(self.cfg["pinned"]))
            r.update_idletasks()
            try:
                hwnd = ctypes.windll.user32.GetParent(r.winfo_id())
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(ctypes.c_int(2)), 4)
            except Exception:
                pass
        bar = tk.Frame(host, bg=BG)
        bar.pack(fill="x", padx=self.pad, pady=(int(10 * S), 0))
        self.title = tk.Label(bar, text="SYK 小组件", bg=BG, fg=FG, font=(F, 9 if master is not None else 12, "bold"))
        self.title.pack(side="left")
        close = tk.Label(bar, text="✕", bg=BG, fg=MUT, cursor="hand2", font=(F, 11))
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.quit())
        for txt, fn in (("全部关闭", lambda: [stop(x) for x in WIDGETS]), ("全部启动", lambda: [start(x) for x in WIDGETS])):
            b = tk.Label(bar, text=txt, bg=BG, fg=ACC, cursor="hand2", font=(F, round(9 * zoom)))
            b.pack(side="right", padx=(0, int(14 * S)))
            b.bind("<Button-1>", lambda e, fn=fn: (fn(), self.rescan_soon(1200)))
        for wdg in (bar, self.title):
            wdg.bind("<ButtonPress-1>", self.drag_start)
            wdg.bind("<B1-Motion>", self.drag)
            wdg.bind("<ButtonRelease-1>", lambda e: self.save())
        self.ch = int((self.ROW * len(WIDGETS) + 2 * self.TOP) * S)
        if self.embedded:
            self.title.config(text="后台程序与开机自启", fg=MUT, font=(F, round(9 * zoom)))
            close.pack_forget()
        self.cv = tk.Canvas(host, width=self.cw, height=self.ch, bg=BG, highlightthickness=0)
        self.cv.pack(padx=self.pad, pady=(int(8 * S), 0))
        self.cv.bind("<Button-1>", self.on_click)
        self.foot = tk.Label(host, text="点右侧开关：运行 = 现在开/关；自启 = 开机时自动打开", bg=BG, fg=MUT, font=(F, round(8 * zoom)))
        self.foot.pack(anchor="w", padx=self.pad, pady=(int(8 * S), int(10 * S)))
        r.update_idletasks()
        if not self.embedded:
            r.geometry(f"{w}x{r.winfo_reqheight()}")
        self.found = {}
        self.draw()
        self.loop()

    def drag_start(self, e):
        self.dx, self.dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def drag(self, e):
        self.root.geometry(f"+{e.x_root - self.dx}+{e.y_root - self.dy}")

    def save(self):
        if self.embedded:
            return
        self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
        json.dump(self.cfg, open(CFG, "w", encoding="utf-8"))

    def quit(self):
        self.save()
        self.root.destroy()

    def loop(self):
        """后台线程扫进程, 扫完回到界面线程重画, 界面不会被卡住。"""
        def work():
            try:
                self.found = scan()
            except Exception:
                pass
            self.root.after(0, self.draw)
        threading.Thread(target=work, daemon=True).start()
        self.root.after(3000, self.loop)

    def rescan_soon(self, ms=700):
        def work():
            try:
                self.found = scan()
            except Exception:
                pass
            self.root.after(0, self.draw)
        self.root.after(ms, lambda: threading.Thread(target=work, daemon=True).start())

    # 两个开关的横向位置(单位: 缩放像素, 从卡片右边往左)
    SW_W, SW_H, RUN_R, AUTO_R = 40, 22, 78, 16

    def sw_box(self, i, right):
        S = self.S
        y0 = (self.TOP + i * self.ROW) * S
        x1 = self.cw - right * S
        cy = y0 + 24 * S
        return x1 - self.SW_W * S, cy - self.SW_H * S / 2, x1, cy + self.SW_H * S / 2

    def draw(self):
        c, S, cw, ch = self.cv, self.S, self.cw, self.ch
        c.delete("all")
        K = 3
        im = Image.new("RGB", (cw * K, ch * K), BG)
        d = ImageDraw.Draw(im)
        state = []
        d.rounded_rectangle([0, 0, cw * K - 1, ch * K - 1], radius=16 * S * K, fill=CARD, outline=EDGE, width=K)
        for i, w in enumerate(WIDGETS):
            run, auto = bool(self.found.get(w["key"])), autostart_on(w)
            state.append((run, auto))
            y0 = (self.TOP + i * self.ROW) * S
            if i:
                d.line([(14 * S * K, y0 * K), ((cw - 14 * S) * K, y0 * K)], fill=EDGE, width=K)
            for on, right in ((run, self.RUN_R), (auto, self.AUTO_R)):
                x0, ya, x1, yb = self.sw_box(i, right)
                d.rounded_rectangle([x0 * K, ya * K, x1 * K, yb * K], radius=(yb - ya) / 2 * K, fill=GREEN if on else TRACK)
                kx = x1 - (yb - ya) / 2 if on else x0 + (yb - ya) / 2
                rk = (yb - ya) / 2 - 3 * S
                d.ellipse([(kx - rk) * K, ((ya + yb) / 2 - rk) * K, (kx + rk) * K, ((ya + yb) / 2 + rk) * K], fill=FG)
        im = im.resize((cw, ch), Image.LANCZOS)
        self.img = ImageTk.PhotoImage(im)
        c.create_image(0, 0, image=self.img, anchor="nw")
        for i, (w, (run, auto)) in enumerate(zip(WIDGETS, state)):
            y0 = (self.TOP + i * self.ROW) * S
            z = self.z
            c.create_oval(14 * S, y0 + 15 * S, 22 * S, y0 + 23 * S, fill=GREEN if run else TRACK, outline="")
            c.create_text(30 * S, y0 + 19 * S, text=w["name"], anchor="w", fill=FG, font=(F, round(10 * z), "bold"))
            c.create_text(30 * S, y0 + 38 * S, text=w["desc"], anchor="w", fill=MUT, font=(F, round(7 * z)))
            for lab, right in (("运行", self.RUN_R), ("自启", self.AUTO_R)):
                x0, ya, x1, yb = self.sw_box(i, right)
                c.create_text((x0 + x1) / 2, yb + 11 * S, text=lab, fill=MUT, font=(F, round(7 * z)))

    def on_click(self, e):
        for i, w in enumerate(WIDGETS):
            for kind, right in (("run", self.RUN_R), ("auto", self.AUTO_R)):
                x0, ya, x1, yb = self.sw_box(i, right)
                if x0 - 4 <= e.x <= x1 + 4 and ya - 6 <= e.y <= yb + 16 * self.S:
                    try:
                        if kind == "run":
                            stop(w) if procs(w) else start(w)
                        else:
                            set_autostart(w, not autostart_on(w))
                        self.foot.config(text="点右侧开关：运行 = 现在开/关；自启 = 开机时自动打开", fg=MUT)
                    except Exception as ex:
                        self.foot.config(text=f"操作失败：{ex}", fg="#e0594b")
                    self.draw()
                    self.rescan_soon(900 if kind == "run" else 50)
                    return


if __name__ == "__main__":
    App().root.mainloop()
