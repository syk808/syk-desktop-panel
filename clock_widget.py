"""中美时间悬浮小窗(与 TokPay 同款外观): 北京时间 + 美国本土四大时区 + 美股开盘状态。只读系统时间, 不联网。"""
import ctypes, json, os, subprocess, sys, tkinter as tk
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageTk

try:  # 高分屏清晰渲染: 必须在创建窗口之前声明 DPI 感知
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "clock_config.json")


def load_cfg():
    try:
        c = json.load(open(CFG, encoding="utf-8"))
    except Exception:
        c = {}
    for k, v in (("pinned", True), ("zoom", 1.0), ("collapsed", False), ("x", None), ("y", None)):
        c.setdefault(k, v)
    return c


ZOOM = min(2.0, max(0.8, float(load_cfg().get("zoom", 1.0))))
if os.environ.get("SYK_ZOOM"):
    ZOOM = float(os.environ["SYK_ZOOM"])


def fs(n):
    return max(6, round(n * ZOOM))


BG, CARD, FG, MUT, TRACK, EDGE = "#161615", "#222220", "#f3f2ee", "#8f8c84", "#34332f", "#2e2d2a"
ACC, GREEN, AMBER = "#6f9bff", "#2fa36b", "#d9a441"
FONT, F = "Segoe UI Variable Text", "Microsoft YaHei UI"
BJ = ZoneInfo("Asia/Shanghai")
NY = ZoneInfo("America/New_York")
ZONES = [("ET", "东部 · 纽约", NY), ("CT", "中部 · 芝加哥", ZoneInfo("America/Chicago")),
         ("MT", "山地 · 丹佛", ZoneInfo("America/Denver")), ("PT", "太平洋 · 洛杉矶", ZoneInfo("America/Los_Angeles"))]
WEEK = "一二三四五六日"


def market(now_ny):
    """美股常规交易时段(不含节假日): 返回 (状态, 颜色, 下一节点说明, 剩余时间)。"""
    def at(d, h, m):
        return d.replace(hour=h, minute=m, second=0, microsecond=0)
    d = now_ny
    if d.weekday() < 5:
        pre, opn, cls, aft = at(d, 4, 0), at(d, 9, 30), at(d, 16, 0), at(d, 20, 0)
        if pre <= d < opn:
            return "盘前", AMBER, "距开盘", opn - d
        if opn <= d < cls:
            return "交易中", GREEN, "距收盘", cls - d
        if cls <= d < aft:
            return "盘后", AMBER, "距盘后结束", aft - d
    nxt = d
    if not (d.weekday() < 5 and d < at(d, 4, 0)):
        nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return "休市", MUT, "距盘前", at(nxt, 4, 0) - d


def hms(td):
    s = max(0, int(td.total_seconds()))
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h // 24}天 {h % 24:02d}:{m:02d}" if h >= 24 else f"{h:02d}:{m:02d}:{s:02d}"


class App:
    HERO_H, MK0, MK1, Z0, ROW = 96, 104, 144, 152, 46

    def __init__(self, master=None, on_resize=None, width=404):
        self.embedded, self.on_resize = master is not None, on_resize
        self.cfg = load_cfg()
        if self.embedded:
            r = self.root = master.winfo_toplevel()
            host = master
            self.cfg["collapsed"] = False
        else:
            r = self.root = tk.Tk()
            host = r
            r.title("中美时间")
            r.configure(bg=BG)
            r.resizable(False, False)
            r.overrideredirect(True)
        self.S = S = max(1.0, r.winfo_fpixels("1i") / 96) * ZOOM
        self.W = w = int(width * S)
        self.pad = int(14 * S)
        self.cw = w - 2 * self.pad
        if not self.embedded:
            x = self.cfg.get("x") if self.cfg.get("x") is not None else r.winfo_screenwidth() - w - 24
            y = self.cfg.get("y") if self.cfg.get("y") is not None else r.winfo_screenheight() - int(470 * S)
            r.geometry(f"{w}x{int(420 * S)}+{x}+{y}")
            r.attributes("-topmost", bool(self.cfg["pinned"]))
            r.update_idletasks()
            try:  # Win11 圆角
                hwnd = ctypes.windll.user32.GetParent(r.winfo_id())
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(ctypes.c_int(2)), 4)
            except Exception:
                pass

        bar = tk.Frame(host, bg=BG)
        bar.pack(fill="x", padx=self.pad, pady=(int(10 * S), 0))
        self.title = tk.Label(bar, text="中美时间", bg=BG, fg=FG, font=(F, fs(12), "bold"))
        self.title.pack(side="left")
        close = tk.Label(bar, text="✕", bg=BG, fg=MUT, cursor="hand2", font=(F, fs(11)))
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.quit())
        for txt, d in (("A+", 0.1), ("A−", -0.1)):
            zb = tk.Label(bar, text=txt, bg=BG, fg=MUT, cursor="hand2", font=(FONT, fs(10), "bold"))
            zb.pack(side="right", padx=(0, int(10 * S)))
            zb.bind("<Button-1>", lambda e, d=d: self.zoom(d))
        self.pin = tk.Label(bar, text="", bg=BG, cursor="hand2", font=(F, fs(10)))
        self.pin.pack(side="right", padx=int(12 * S))
        self.pin.bind("<Button-1>", lambda e: self.toggle_pin())
        self.fold = tk.Label(bar, text="", bg=BG, fg=MUT, cursor="hand2", font=(F, fs(10)))
        self.fold.pack(side="right")
        self.fold.bind("<Button-1>", lambda e: self.toggle_fold())
        for wdg in (bar, self.title):
            wdg.bind("<ButtonPress-1>", self.drag_start)
            wdg.bind("<B1-Motion>", self.drag)
            wdg.bind("<ButtonRelease-1>", lambda e: self.save())

        if self.embedded:   # 合并面板里只留一行小标题, 和其它栏的标题对齐
            for wdg in bar.winfo_children():
                wdg.pack_forget()
            self.title.config(text="时间", fg=MUT, font=(F, fs(9)))
            self.title.pack(side="left")
        self.cv = tk.Canvas(host, width=self.cw, height=10, bg=BG, highlightthickness=0)
        self.cv.pack(padx=self.pad, pady=(int(8 * S), int(12 * S)))
        self.cv.bind("<ButtonPress-1>", self.drag_start)
        self.cv.bind("<B1-Motion>", self.drag)
        self.cv.bind("<ButtonRelease-1>", lambda e: self.save())
        r.bind("<Control-MouseWheel>", lambda e: self.zoom(0.1 if e.delta > 0 else -0.1))
        self.refresh_pin()
        self.build()
        self.tick()

    # ---- 窗口行为
    def drag_start(self, e):
        self.dx, self.dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def drag(self, e):
        self.root.geometry(f"+{e.x_root - self.dx}+{e.y_root - self.dy}")

    def save(self):
        if self.embedded:
            return
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

    def toggle_fold(self):
        self.cfg["collapsed"] = not self.cfg["collapsed"]
        self.save()
        self.build()
        self.tick(once=True)

    def zoom(self, d):
        if self.embedded:
            return
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

    # ---- 绘制: 背景卡片只画一次, 每秒只改文字
    def rr(self, d, box, fill=None, outline=None, width=0, radius=12):
        K, S = self.K, self.S
        d.rounded_rectangle([v * K for v in box], radius=radius * S * K, fill=fill, outline=outline, width=int(width * K))

    def build(self):
        c, S, cw = self.cv, self.S, self.cw
        c.delete("all")
        fold = self.cfg["collapsed"]
        self.fold.config(text="展开 ▾" if fold else "收起 ▴")
        self.ch = ch = int((self.MK1 if fold else self.Z0 + self.ROW * len(ZONES) + 10) * S)
        c.config(height=ch)
        self.K = K = 3
        im = Image.new("RGB", (cw * K, ch * K), BG)
        d = ImageDraw.Draw(im)
        self.rr(d, (0, 0, cw, self.HERO_H * S), fill=CARD, outline=EDGE, width=1, radius=16)
        self.rr(d, (0, self.MK0 * S, cw, self.MK1 * S), fill=CARD, outline=EDGE, width=1, radius=14)
        if not fold:
            z0 = self.Z0 * S
            self.rr(d, (0, z0, cw, z0 + (self.ROW * len(ZONES) + 10) * S), fill=CARD, outline=EDGE, width=1, radius=16)
            for i in range(len(ZONES)):
                y = z0 + (5 + self.ROW * i) * S
                self.rr(d, (14 * S, y + 11 * S, 50 * S, y + 35 * S), fill=TRACK, radius=8)
                if i:
                    d.line([(14 * S * K, y * K), ((cw - 14 * S) * K, y * K)], fill=EDGE, width=K)
        im = im.resize((cw, ch), Image.LANCZOS)
        self.img = ImageTk.PhotoImage(im)
        c.create_image(0, 0, image=self.img, anchor="nw")

        c.create_text(18 * S, 20 * S, text="中国 · 北京", anchor="w", fill=MUT, font=(F, fs(9)))
        self.t_bj = c.create_text(16 * S, 56 * S, text="", anchor="w", fill=FG, font=(FONT, fs(30), "bold"))
        self.t_date = c.create_text(cw - 18 * S, 24 * S, text="", anchor="e", fill=FG, font=(F, fs(11), "bold"))
        c.create_text(cw - 18 * S, 46 * S, text="UTC+8", anchor="e", fill=MUT, font=(FONT, fs(9)))
        self.t_lead = c.create_text(cw - 18 * S, 66 * S, text="", anchor="e", fill=MUT, font=(F, fs(8)))
        my = (self.MK0 + self.MK1) / 2 * S
        self.dot = c.create_oval(18 * S, my - 4 * S, 26 * S, my + 4 * S, fill=MUT, outline="")
        self.t_mk = c.create_text(34 * S, my, text="", anchor="w", fill=FG, font=(F, fs(10), "bold"))
        self.t_cd = c.create_text(cw - 18 * S, my, text="", anchor="e", fill=MUT, font=(F, fs(9)))
        self.rows = []
        if not fold:
            for i, (tag, name, _tz) in enumerate(ZONES):
                y = (self.Z0 + 5 + self.ROW * i + 23) * S
                c.create_text(32 * S, y, text=tag, fill=ACC, font=(FONT, fs(9), "bold"))
                c.create_text(60 * S, y, text=name, anchor="w", fill=FG, font=(F, fs(10)))
                t = c.create_text(cw - 104 * S, y, text="", anchor="e", fill=FG, font=(FONT, fs(17), "bold"))
                a = c.create_text(cw - 16 * S, y - 8 * S, text="", anchor="e", fill=MUT, font=(F, fs(8)))
                b = c.create_text(cw - 16 * S, y + 9 * S, text="", anchor="e", fill=MUT, font=(F, fs(8)))
                self.rows.append((t, a, b))
        self.root.update_idletasks()
        if self.embedded:
            if self.on_resize:
                self.on_resize()
        else:
            self.root.geometry(f"{self.W}x{self.root.winfo_reqheight()}")

    def tick(self, once=False):
        c = self.cv
        now = datetime.now(BJ)
        c.itemconfig(self.t_bj, text=now.strftime("%H:%M:%S"))
        c.itemconfig(self.t_date, text=f"{now.month}月{now.day}日 周{WEEK[now.weekday()]}")
        offs = [int((now.utcoffset() - now.astimezone(tz).utcoffset()).total_seconds() // 3600) for _t, _n, tz in ZONES]
        c.itemconfig(self.t_lead, text=f"比美国快 {min(offs)}–{max(offs)} 小时")
        state, col, lab, left = market(now.astimezone(NY))
        c.itemconfig(self.dot, fill=col)
        c.itemconfig(self.t_mk, text=f"美股 · {state}", fill=FG if state != "休市" else MUT)
        c.itemconfig(self.t_cd, text=f"{lab} {hms(left)}")
        for (t, a, b), (_tag, _name, tz), off in zip(self.rows, ZONES, offs):
            z = now.astimezone(tz)
            dd = (z.date() - now.date()).days
            day = {0: "今天", -1: "昨天", 1: "明天"}.get(dd, f"{dd:+d}天")
            uo = int(z.utcoffset().total_seconds() // 3600)
            c.itemconfig(t, text=z.strftime("%H:%M:%S"))
            c.itemconfig(a, text=f"UTC{uo:+d} · {day}")
            c.itemconfig(b, text=f"中国 +{off}h")
        if not once:
            self.root.after(1000 - now.microsecond // 1000 + 5, self.tick)


if __name__ == "__main__":
    App().root.mainloop()
