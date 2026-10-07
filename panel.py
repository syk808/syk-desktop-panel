"""SYK 面板: 把 TokPay(回本)、中美时间、插件管理 合进一个窗口, 顶部标签切换。
三个面板的代码还在各自的文件里(tokpay_widget.py / clock_widget.py / hub.py), 这里只负责外框和切换。"""
import ctypes, json, os, subprocess, sys, tkinter as tk

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "panel_config.json")
# tokpay_widget.py sits next to this file in the repo; SYK_TOKPAY_DIR overrides it for a split install
TOKPAY_DIR = os.environ.get("SYK_TOKPAY_DIR") or HERE


def load_cfg():
    try:
        c = json.load(open(CFG, encoding="utf-8"))
    except Exception:
        c = {}
    for k, v in (("pinned", True), ("zoom", 1.1), ("tab", "pay"), ("mode", "all"), ("x", None), ("y", None)):
        c.setdefault(k, v)
    return c


CFGD = load_cfg()
ZOOM = min(2.0, max(0.8, float(CFGD["zoom"])))
os.environ["SYK_ZOOM"] = str(ZOOM)          # 三个面板统一用这个缩放
sys.path.insert(0, TOKPAY_DIR)
os.chdir(TOKPAY_DIR)
import tokpay_widget, clock_widget, hub, market_widget, loss_widget     # noqa: E402
from datetime import datetime

BG, FG, MUT, TRACK, PILL = "#161615", "#f3f2ee", "#8f8c84", "#34332f", "#3b3a36"
F, FONT = "Microsoft YaHei UI", "Segoe UI Variable Text"
TABS = (("mkt", "行情"), ("loss", "亏损"), ("pay", "回本"), ("clock", "时间"), ("hub", "管理"))
MKT_W, COL_W = 268, 440      # 并排模式: 行情栏、亏损栏窄一点, 回本栏和右栏等宽


def fs(n):
    return max(6, round(n * ZOOM))


class Panel:
    def __init__(self):
        self.cfg = CFGD
        r = self.root = tk.Tk()
        r.title("SYK 面板")
        r.configure(bg=BG)
        r.resizable(False, False)
        r.overrideredirect(True)
        try:
            r.iconbitmap(os.path.join(TOKPAY_DIR, "icon.ico"))
        except Exception:
            pass
        self.S = S = max(1.0, r.winfo_fpixels("1i") / 96) * ZOOM
        self.all = self.cfg.get("mode") != "tabs"      # all = 三块并排都显示; tabs = 标签切换
        self.W = int((MKT_W * 2 + COL_W * 2) * S) if self.all else int(440 * S)
        x = self.cfg["x"] if self.cfg["x"] is not None else r.winfo_screenwidth() - self.W - 24
        y = self.cfg["y"] if self.cfg["y"] is not None else 60
        r.geometry(f"+{x}+{y}")
        r.attributes("-topmost", bool(self.cfg["pinned"]))
        r.update_idletasks()
        try:  # Win11 圆角
            hwnd = ctypes.windll.user32.GetParent(r.winfo_id())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(ctypes.c_int(2)), 4)
        except Exception:
            pass

        bar = tk.Frame(r, bg=BG, width=self.W)
        bar.pack(fill="x", padx=int(14 * S), pady=(int(10 * S), 0))
        self.title = tk.Label(bar, text="SYK", bg=BG, fg=FG, font=(FONT, fs(13), "bold"))
        self.title.pack(side="left")
        seg = tk.Frame(bar, bg=TRACK)
        if not self.all:
            seg.pack(side="left", padx=(int(12 * S), 0))
        mode = tk.Label(bar, text="切到标签模式" if self.all else "切到并排模式", bg=BG, fg=MUT, cursor="hand2", font=(F, fs(9)))
        mode.pack(side="left", padx=(int(14 * S), 0))
        mode.bind("<Button-1>", lambda e: self.switch_mode())
        self.tabs = {}
        for key, lab in TABS:
            b = tk.Label(seg, text=lab, bg=TRACK, fg=MUT, cursor="hand2", font=(F, fs(10)), padx=int(11 * S), pady=int(3 * S))
            b.pack(side="left", padx=1, pady=1)
            b.bind("<Button-1>", lambda e, k=key: self.show(k))
            self.tabs[key] = b
        close = tk.Label(bar, text="✕", bg=BG, fg=MUT, cursor="hand2", font=(F, fs(11)))
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.quit())
        mini = tk.Label(bar, text="—", bg=BG, fg=MUT, cursor="hand2", font=(F, fs(11), "bold"))
        mini.pack(side="right", padx=(0, int(12 * S)))
        mini.bind("<Button-1>", lambda e: self.minimize())
        for txt, d in (("A+", 0.1), ("A−", -0.1)):
            zb = tk.Label(bar, text=txt, bg=BG, fg=MUT, cursor="hand2", font=(FONT, fs(10), "bold"))
            zb.pack(side="right", padx=(0, int(10 * S)))
            zb.bind("<Button-1>", lambda e, d=d: self.zoom(d))
        self.pin = tk.Label(bar, text="", bg=BG, cursor="hand2", font=(F, fs(10)))
        self.pin.pack(side="right", padx=int(10 * S))
        self.pin.bind("<Button-1>", lambda e: self.toggle_pin())
        for wdg in (bar, self.title):
            wdg.bind("<ButtonPress-1>", self.drag_start)
            wdg.bind("<B1-Motion>", self.drag)
            wdg.bind("<ButtonRelease-1>", lambda e: self.save())
        r.bind("<Control-MouseWheel>", lambda e: self.zoom(0.1 if e.delta > 0 else -0.1))

        self.current = None
        if self.all:
            body = tk.Frame(r, bg=BG)
            body.pack(fill="both")
            right = tk.Frame(body, bg=BG)
            self.frames = {"mkt": tk.Frame(body, bg=BG), "loss": tk.Frame(body, bg=BG), "pay": tk.Frame(body, bg=BG),
                           "clock": tk.Frame(right, bg=BG), "hub": tk.Frame(right, bg=BG)}
            for k in ("mkt", "loss", "pay"):          # 行情 | 亏损 | 回本 | 时间+管理, 各占一列
                self.frames[k].pack(side="left", anchor="n")
            right.pack(side="left", anchor="n")
            self.frames["clock"].pack(anchor="n")
            self.frames["hub"].pack(anchor="n")
            side = COL_W
        else:
            self.frames = {k: tk.Frame(r, bg=BG, width=self.W) for k, _ in TABS}
            side = 440
        self.apps = {
            "mkt": market_widget.App(master=self.frames["mkt"], on_resize=self.fit, width=MKT_W if self.all else 440),
            "loss": loss_widget.App(master=self.frames["loss"], on_resize=self.fit, width=MKT_W if self.all else 440),
            "pay": tokpay_widget.App(master=self.frames["pay"], on_resize=self.fit),
            "clock": clock_widget.App(master=self.frames["clock"], on_resize=self.fit, width=side),
            "hub": hub.App(master=self.frames["hub"], on_resize=self.fit, width=side),
        }
        self.refresh_pin()
        if os.environ.get("SYK_AUTOMIN"):        # 自测用: 启动几秒后自动最小化
            r.after(int(os.environ["SYK_AUTOMIN"]) * 1000, self.minimize)
        if self.all:
            self.fit()
        else:
            self.show(self.cfg["tab"] if self.cfg["tab"] in self.frames else "pay")

    def fit(self):
        """内容高度变了(切标签、展开模型列表)就让窗口跟着变; 并排模式下顺手把三栏底部对齐。"""
        if getattr(self, "_fitting", False) or not hasattr(self, "apps"):
            return
        self._fitting = True
        try:
            self.root.update_idletasks()
            if self.all:
                S, f, pay, mkt = self.S, self.frames, self.apps["pay"], self.apps["mkt"]
                right = f["clock"].winfo_reqheight() + f["hub"].winfo_reqheight()
                natural = f["pay"].winfo_reqheight() - int(pay.grow * S)      # 回本栏不加高时的高度
                target = max(natural, right)
                extra = int((target - natural) / S)
                if extra != pay.grow:
                    pay.set_extra(extra)
                chrome = f["mkt"].winfo_reqheight() - mkt.cv.winfo_reqheight()   # 行情栏标题行 + 上下留白
                mkt.set_height(target - chrome)
                loss = self.apps["loss"]
                loss.set_height(target - (f["loss"].winfo_reqheight() - loss.cv.winfo_reqheight()))
                self.root.update_idletasks()
            self.root.geometry("")
            self.keep_on_screen()
        finally:
            self._fitting = False

    def keep_on_screen(self):
        """面板变宽后右边别跑出屏幕(按所有显示器拼起来的范围算)。"""
        r = self.root
        r.update_idletasks()
        u = ctypes.windll.user32
        vx, vw = u.GetSystemMetrics(76), u.GetSystemMetrics(78)
        x, w = r.winfo_x(), r.winfo_width()
        if x + w > vx + vw:
            r.geometry(f"+{max(vx, vx + vw - w - 24)}+{r.winfo_y()}")

    def show(self, key):
        if self.current:
            self.frames[self.current].pack_forget()
        self.frames[key].pack(fill="both")
        self.current = self.cfg["tab"] = key
        for k, b in self.tabs.items():
            b.config(bg=PILL if k == key else TRACK, fg=FG if k == key else MUT, font=(F, fs(10), "bold" if k == key else "normal"))
        self.fit()
        self.save()

    def switch_mode(self):
        self.cfg["mode"] = "tabs" if self.all else "all"
        self.save()
        subprocess.Popen([sys.executable, os.path.abspath(__file__)], cwd=HERE)
        self.root.destroy()

    # ---- 最小化: 缩成屏幕右下角的一小条, 点一下还原
    def minimize(self):
        if getattr(self, "mini", None):
            return
        self.save()
        S = self.S
        m = self.mini = tk.Toplevel(self.root)
        m.overrideredirect(True)
        m.configure(bg="#222220")
        m.attributes("-topmost", True)
        self.mini_lab = tk.Label(m, text="", bg="#222220", fg=FG, cursor="hand2", font=(FONT, fs(10), "bold"), padx=int(14 * S), pady=int(7 * S))
        self.mini_lab.pack()
        self.mini_lab.bind("<Button-1>", lambda e: self.restore())
        self.root.withdraw()
        self.mini_tick()
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.windll.user32.GetParent(m.winfo_id()), 33, ctypes.byref(ctypes.c_int(2)), 4)
        except Exception:
            pass

    def mini_tick(self):
        if not getattr(self, "mini", None):
            return
        parts = ["SYK", datetime.now().strftime("%H:%M")]
        try:
            btc = self.apps["mkt"].btc()
            if btc:
                parts.append(f"BTC {btc:,.0f}")
            parts.append(f"回本 {self.apps['pay'].vendor_totals('all')[2]:.1f}×")
        except Exception:
            pass
        self.mini_lab.config(text="   ·   ".join(parts))
        m = self.mini
        m.update_idletasks()
        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
        wa = RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(wa), 0)   # 工作区(不含任务栏)
        m.geometry(f"+{wa.r - m.winfo_reqwidth() - int(12 * self.S)}+{wa.b - m.winfo_reqheight() - int(10 * self.S)}")
        self.root.after(5000, self.mini_tick)

    def restore(self):
        m, self.mini = self.mini, None
        if m:
            m.destroy()
        self.root.deiconify()
        self.root.attributes("-topmost", bool(self.cfg["pinned"]))

    def drag_start(self, e):
        self.dx, self.dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def drag(self, e):
        self.root.geometry(f"+{e.x_root - self.dx}+{e.y_root - self.dy}")

    def save(self):
        self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
        json.dump(self.cfg, open(CFG, "w", encoding="utf-8"))

    def toggle_pin(self):
        self.cfg["pinned"] = not self.cfg["pinned"]
        self.root.attributes("-topmost", self.cfg["pinned"])
        self.refresh_pin()
        self.save()

    def refresh_pin(self):
        on = self.cfg["pinned"]
        self.pin.config(text="📌 已置顶" if on else "📌 置顶", fg="#d97757" if on else MUT)

    def zoom(self, d):
        z = round(min(2.0, max(0.8, ZOOM + d)), 2)
        if z == ZOOM:
            return
        self.cfg["zoom"] = z
        self.save()
        subprocess.Popen([sys.executable, os.path.abspath(__file__)], cwd=HERE)
        self.root.destroy()

    def quit(self):
        self.save()
        self.root.destroy()


if __name__ == "__main__":
    Panel().root.mainloop()
