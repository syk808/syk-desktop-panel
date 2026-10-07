"""TokPay 悬浮小窗:点击图标弹出,可置顶挂在屏幕上。数据只读本机。"""
import hermes_source
import ctypes, json, math, os, subprocess, sys, threading, time, tkinter as tk
from tkinter import simpledialog
from datetime import datetime, timedelta
from collections import defaultdict
from PIL import Image, ImageDraw, ImageTk

try:  # 高分屏清晰渲染:必须在创建窗口之前声明 DPI 感知
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "config.json")
CACHE = os.path.join(HERE, "cache.json")
try:
    ZOOM = min(2.0, max(0.8, float(json.load(open(CFG, encoding="utf-8")).get("zoom", 1.0))))
except Exception:
    ZOOM = 1.0
if os.environ.get("SYK_ZOOM"):      # 嵌进合并面板时由面板统一缩放
    ZOOM = float(os.environ["SYK_ZOOM"])


def fs(n):
    return max(6, round(n * ZOOM))

BG, CARD, FG, MUT, TRACK = "#161615", "#222220", "#f3f2ee", "#8f8c84", "#34332f"
FONT = "Segoe UI Variable Text"
COLS = ("#d97757", "#4b7bec", "#2fa36b")
CLAUDE = os.path.expanduser("~/.claude/projects")
CODEX = os.path.expanduser("~/.codex/sessions")


# 套餐按月份生效:[起始月, 月费],同一厂商后面的覆盖前面的
DEFAULT_HISTORY = {
    "claude": [["2000-01", 200], ["2026-09", 20]],
    "openai": [["2000-01", 200], ["2026-09", 100]],
    "xai": [["2000-01", 30]],
}


def load_cfg():
    try:
        c = json.load(open(CFG, encoding="utf-8"))
        if "history" in c:
            return c
    except Exception:
        c = {}
    c.pop("plans", None)
    c.update({"history": DEFAULT_HISTORY, "view": c.get("view", "all"), "pinned": c.get("pinned", True),
              "x": c.get("x"), "y": c.get("y")})
    return c


TOKSCALE = os.path.join(HERE, "tokscale", "node_modules", ".bin", "tokscale.cmd")

# 套餐目录,照 TokNotch 的 PlanCatalog(官方标价,美元/月)
VENDORS = [("all", "全部"), ("claude", "Claude"), ("openai", "GPT"), ("xai", "Grok")]
PLANS = {
    "claude": [("Claude Pro", 20), ("Claude Max 5×", 100), ("Claude Max 20×", 200), ("Claude Team", 30)],
    "openai": [("ChatGPT Plus", 20), ("ChatGPT Pro", 200), ("ChatGPT Business", 25)],
    "xai": [("SuperGrok", 30), ("SuperGrok Heavy", 300)],
}


GROK_PRICES = [
    ("grok-4.7", (2.0, 0.5, 6.0)),
    ("grok-4.6", (2.0, 0.5, 6.0)),
    ("grok-4.5", (2.0, 0.3, 6.0)),
    ("grok-4.3", (1.25, 0.2, 2.5)),
    ("grok-4.20", (1.25, 0.2, 2.5)),
]
XAI_TOKENS_ONLY = False


def grok_cost(model, i, o, cr, cw):
    for key, (pin, pcache, pout) in GROK_PRICES:
        if key in model.lower():
            return ((i + cw) * pin + cr * pcache + o * pout) / 1e6
    return None


def vendor_of(client, model):
    m = model.lower()
    if client == "claude" or "claude" in m:
        return "claude"
    if client == "codex" or m.startswith(("gpt", "o1", "o3", "o4", "codex", "chatgpt")):
        return "openai"
    if "grok" in m or client == "grok":
        return "xai"
    return "other"


def collect():
    """tokscale graph(金额与价格以它为准) + WSL 里 Hermes 的用量。"""
    out = subprocess.run([TOKSCALE, "graph", "--no-spinner"], capture_output=True, timeout=300,
                         creationflags=0x08000000).stdout
    g = json.loads(out.decode("utf-8"))
    days = defaultdict(lambda: defaultdict(float))
    toks = defaultdict(lambda: defaultdict(int))
    models = defaultdict(lambda: [0.0, 0])
    mdays = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))   # 日期 -> 模型键 -> [金额, token]
    for d in g["contributions"]:
        for c in d["clients"]:
            v = vendor_of(c["client"], c["modelId"])
            t = c["tokens"]
            n = t["input"] + t["output"] + t["cacheRead"] + t["cacheWrite"]
            days[d["date"]][v] += c["cost"]
            toks[d["date"]][v] += n
            m = models[f"{v}|{c['client']}|{c['modelId']}|"]
            m[0] += c["cost"]
            m[1] += n
            md = mdays[d["date"]][f"{v}|{c['client']}|{c['modelId']}"]
            md[0] += c["cost"]
            md[1] += n
    # 每个模型在 tokscale 里的平均单价(美元/token),给 Hermes 的同名模型折算用
    rate = {}
    vend_cost, vend_tok = defaultdict(float), defaultdict(int)
    for k, (cost, n) in models.items():
        v, _cl, model, _f = k.split("|")
        if n and cost:
            rate[model] = cost / n
        vend_cost[v] += cost
        vend_tok[v] += n
    for row_day, model, i, o, cr, cw in hermes_source.read_sessions():
        n = i + o + cr + cw
        v = vendor_of("hermes", model)
        cost = grok_cost(model, i, o, cr, cw) if v == "xai" else None
        if cost is None:
            r = rate.get(model)
            if r is None and v in ("claude", "openai") and vend_tok[v]:
                r = vend_cost[v] / vend_tok[v]
            cost = n * r if r else 0.0
        days[row_day][v] += cost
        toks[row_day][v] += n
        m = models[f"{v}|hermes|{model}|"]
        m[0] += cost
        m[1] += n
        md = mdays[row_day][f"{v}|hermes|{model}"]
        md[0] += cost
        md[1] += n
    cfg = load_cfg()
    wk, since = cfg.get("grok_weekly_usd"), cfg.get("grok_full_since")
    if wk and since:
        hermes_cost = sum(d.get("xai", 0) for d in days.values())
        day, end, n = datetime.strptime(since, "%Y-%m-%d").date(), datetime.now().date(), 0
        while day <= end:
            days[day.isoformat()]["xai"] = wk / 7
            day += timedelta(1)
            n += 1
        gap = wk / 7 * n - hermes_cost
        models["xai|校准|Grok 周额度满额估算(补差)|"] = [gap, 0]
    extra = {}
    target = cfg.get("gpt_total_tokens") or 0
    if target and vend_tok["openai"]:
        local = sum(n for k, (c, n) in models.items() if k.startswith("openai|"))
        gap = target - local
        if gap > 0:
            cost = gap * vend_cost["openai"] / vend_tok["openai"]
            extra["openai"] = {"tokens": gap, "cost": cost}
            models["openai|校准|GPT 未归档用量(估算)|"] = [cost, gap]
    # 有用量却算不出金额的模型,标为无价格
    for k in list(models):
        c, tok = models[k]
        if c == 0 and tok > 0:
            models[k[:-1] + "?"] = models.pop(k)
    return {"days": days, "toks": toks, "models": models, "extra": extra, "mdays": mdays}


def ftok(n):
    if n >= 1e8:
        return f"{n / 1e8:.2f}亿"
    if n >= 1e4:
        return f"{n / 1e4:.0f}万"
    return f"{n:.0f}"


def fm(n):
    return f"${n:,.0f}" if n >= 1000 else f"${n:,.2f}"


class App:
    """布局:顶栏 / 总回本 / 三个厂商卡片(可点选) / 所选范围的 30 天柱状图与今日、本月、累计 / 底栏。"""

    VKEYS = ("claude", "openai", "xai")
    VNAMES = {"claude": "Claude", "openai": "GPT", "xai": "Grok", "all": "合计"}
    ACCENT = "#e9e6dc"

    def __init__(self, master=None, on_resize=None):
        self.embedded, self.on_resize = master is not None, on_resize
        self.grow = 0          # 合并面板为了三栏底部对齐, 给图表面板加的高度(缩放像素)
        self.cfg = load_cfg()
        if self.cfg.get("view") not in ("all",) + self.VKEYS:
            self.cfg["view"] = "all"
        try:
            c = json.load(open(CACHE, encoding="utf-8"))
            self.days, self.models, self.toks, self.extra = c["days"], c["models"], c.get("toks", {}), c.get("extra", {})
            self.mdays = c.get("mdays", {})
            self.status = "缓存数据,更新中…"
        except Exception:
            self.days, self.models, self.toks, self.extra = {}, {}, {}, {}
            self.mdays = {}
            self.status = "首次读取中(约半分钟)…"
        if self.embedded:
            r = self.root = master.winfo_toplevel()
            host = master
            self.S = S = max(1.0, r.winfo_fpixels("1i") / 96) * ZOOM
            self.W = w = int(440 * S)
        else:
            r = self.root = tk.Tk()
            host = r
            r.title("TokPay")
            r.configure(bg=BG)
            r.resizable(False, False)
            try:
                r.iconbitmap(os.path.join(HERE, "icon.ico"))
            except Exception:
                pass
            r.overrideredirect(True)
            self.S = S = max(1.0, r.winfo_fpixels("1i") / 96) * ZOOM
            self.W = w = int(440 * S)
            x = self.cfg.get("x") or r.winfo_screenwidth() - w - 24
            y = self.cfg.get("y") or 60
            r.geometry(f"{w}x{int(506 * S)}+{x}+{y}")
            r.attributes("-topmost", bool(self.cfg["pinned"]))
            r.update_idletasks()
            try:  # Win11 圆角
                hwnd = ctypes.windll.user32.GetParent(r.winfo_id())
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(ctypes.c_int(2)), 4)
            except Exception:
                pass

        # 顶栏
        bar = tk.Frame(host, bg=BG)
        bar.pack(fill="x", padx=int(14 * S), pady=(int(10 * S), 0))
        self.title = tk.Label(bar, text="TokPay", bg=BG, fg=FG, font=(FONT, fs(13), "bold"))
        self.title.pack(side="left")
        close = tk.Label(bar, text="✕", bg=BG, fg=MUT, cursor="hand2", font=("Microsoft YaHei UI", fs(11)))
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.quit())
        for txt, d in (("A+", 0.1), ("A−", -0.1)):
            zb = tk.Label(bar, text=txt, bg=BG, fg=MUT, cursor="hand2", font=(FONT, fs(10), "bold"))
            zb.pack(side="right", padx=(0, int(10 * S)))
            zb.bind("<Button-1>", lambda e, d=d: self.zoom(d))
        self.pin = tk.Label(bar, text="", bg=BG, cursor="hand2", font=("Microsoft YaHei UI", fs(10)))
        self.pin.pack(side="right", padx=int(12 * S))
        self.pin.bind("<Button-1>", lambda e: self.toggle_pin())
        self.rbtn = tk.Label(bar, text="↻ 刷新", bg=BG, fg=MUT, cursor="hand2", font=("Microsoft YaHei UI", fs(10)))
        self.rbtn.pack(side="right")
        self.rbtn.bind("<Button-1>", lambda e: self.refresh())
        for wdg in (bar, self.title):
            wdg.bind("<ButtonPress-1>", self.drag_start)
            wdg.bind("<B1-Motion>", self.drag)
            wdg.bind("<ButtonRelease-1>", lambda e: self.save())
        if self.embedded:   # 合并面板自带标题/置顶/缩放/关闭, 这里只留刷新
            for wdg in bar.winfo_children():
                if wdg is not self.rbtn:
                    wdg.pack_forget()
            self.title.config(text="AI 订阅回本", fg=MUT, font=("Microsoft YaHei UI", fs(9)))
            self.title.pack(side="left")
            self.rbtn.config(font=("Microsoft YaHei UI", fs(9)))

        # 主画布
        self.pad = int(14 * S)
        self.cw = w - 2 * self.pad
        self.ch = int(440 * S)
        self.cv = tk.Canvas(host, width=self.cw, height=self.ch, bg=BG, highlightthickness=0)
        self.cv.pack(padx=self.pad, pady=(int(8 * S), 0))
        self.cv.bind("<Button-1>", self.on_click)

        # 底栏
        foot = tk.Frame(host, bg=BG)
        foot.pack(fill="x", padx=self.pad, pady=(int(6 * S), int(8 * S)))
        self.foot = tk.Label(foot, text="", bg=BG, fg=MUT, font=("Microsoft YaHei UI", fs(9)), justify="left")
        self.foot.pack(side="left")
        self.mbtn = tk.Label(foot, text="按模型 ▾", bg=BG, fg=COLS[1], cursor="hand2", font=("Microsoft YaHei UI", fs(10)))
        self.mbtn.pack(side="right")
        self.mbtn.bind("<Button-1>", lambda e: self.toggle_models())
        self.mlist = tk.Frame(host, bg=BG)
        self.show_models = False
        r.bind("<Control-MouseWheel>", lambda e: self.zoom(0.1 if e.delta > 0 else -0.1))
        self.refresh_pin()
        self.draw()
        self.loop()

    # ---- 交互
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

    def on_click(self, e):
        S = self.S
        py = self.PY * S
        # 厂商卡片:点选;再点一次已选中的回到合计
        if self.CY0 * S <= e.y <= self.CY1 * S:
            gap = 8 * S
            cardw = (self.cw - 2 * gap) / 3
            i = int(e.x // (cardw + gap))
            if 0 <= i < 3 and e.x <= i * (cardw + gap) + cardw:
                k = self.VKEYS[i]
                self.cfg["view"] = "all" if self.cfg["view"] == k else k
                self.save()
                self.draw()
        # 范围面板标题行:日 / 周 / 月 切换
        elif py + 6 * S <= e.y <= py + 38 * S and self.SEG_X * S <= e.x < (self.SEG_X + 3 * self.SEG_W) * S:
            i = int((e.x - self.SEG_X * S) // (self.SEG_W * S))
            self.cfg["gran"] = ("day", "week", "month")[min(2, max(0, i))]
            self.save()
            self.draw()
        # 范围面板右上角:改套餐
        elif py <= e.y <= py + 38 * S and e.x >= self.cw * 0.62:
            self.set_plan(e)

    def price_at(self, vendor, month):
        price = 0
        for start, p in self.cfg["history"].get(vendor, []):
            if start <= month:
                price = p
        return price

    def plan_for(self, view, month=None):
        month = month or datetime.now().strftime("%Y-%m")
        vs = self.VKEYS if view == "all" else (view,)
        return sum(self.price_at(v, month) for v in vs)

    def paid_total(self, view):
        """每个厂商从它有用量的第一个月起(或 paid_from 指定的月份),到本月为止实际付的套餐费之和。"""
        vs = self.VKEYS if view == "all" else (view,)
        ny, nm = datetime.now().year, datetime.now().month
        paid = 0
        for v in vs:
            firsts = [k[:7] for k, d in self.toks.items() if d.get(v, 0) > 0]
            if not firsts:
                firsts = [datetime.now().strftime("%Y-%m")]
            start = self.cfg.get("paid_from", {}).get(v) or min(firsts)
            y, m = map(int, start.split("-"))
            while (y, m) <= (ny, nm):
                paid += self.price_at(v, f"{y}-{m:02d}")
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return paid

    def day_total(self, D, view):
        return sum(D.values()) if view == "all" else D.get(view, 0)

    def drag_start(self, e):
        self.dx, self.dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def drag(self, e):
        self.root.geometry(f"+{e.x_root - self.dx}+{e.y_root - self.dy}")

    def save(self):
        if not self.embedded:
            self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
        json.dump(self.cfg, open(CFG, "w", encoding="utf-8"))

    def toggle_pin(self):
        self.cfg["pinned"] = not self.cfg["pinned"]
        self.root.attributes("-topmost", self.cfg["pinned"])
        self.refresh_pin()
        self.save()

    def refresh_pin(self):
        self.pin.config(text="📌 已挂起" if self.cfg["pinned"] else "📍 挂起", fg=COLS[0] if self.cfg["pinned"] else MUT)

    def set_plan(self, e=None):
        v = self.cfg["view"]
        if v == "all":
            return
        m = tk.Menu(self.root, tearoff=0)
        for name, price in PLANS[v]:
            m.add_command(label=f"{name}  ${price:g}", command=lambda p=price: self.apply_plan(p))
        m.add_separator()
        m.add_command(label="选择后从本月起生效,之前月份不变", state="disabled")
        m.add_command(label="自定义金额…", command=self.custom_plan)
        x = self.root.winfo_rootx() + (int(e.x) if e else 0)
        y = self.root.winfo_rooty() + (int(e.y) if e else 0)
        m.tk_popup(x, y)

    def apply_plan(self, val):
        h = self.cfg["history"].setdefault(self.cfg["view"], [])
        cur = datetime.now().strftime("%Y-%m")
        h[:] = [e for e in h if e[0] != cur] + [[cur, val]]
        h.sort()
        self.save()
        self.draw()

    def custom_plan(self):
        self.root.attributes("-topmost", False)
        v = simpledialog.askfloat("套餐月费", "套餐月费(美元):", initialvalue=self.plan_for(self.cfg["view"]), minvalue=1, parent=self.root)
        self.root.attributes("-topmost", self.cfg["pinned"])
        if v:
            self.apply_plan(v)

    def toggle_models(self):
        self.show_models = not self.show_models
        self.mbtn.config(text="按模型 ▴" if self.show_models else "按模型 ▾")
        if self.show_models:
            self.mlist.pack(fill="x", padx=self.pad, pady=(0, int(8 * self.S)))
        else:
            self.mlist.pack_forget()
        self.draw_models()

    def draw_models(self):
        for w in self.mlist.winfo_children():
            w.destroy()
        if self.show_models:
            view = self.cfg["view"]
            gran = self.cfg.get("gran", "day")
            today = datetime.now().date()
            if gran == "week":
                monday = today - timedelta(today.weekday())
                keys, plab = [(monday + timedelta(j)).isoformat() for j in range(7)], "本周"
            elif gran == "month":
                keys, plab = [k for k in self.mdays if k.startswith(today.isoformat()[:7])], "本月"
            else:
                keys, plab = [today.isoformat()], "今日"
            per = defaultdict(float)
            for k in keys:
                for mk, (c, _n) in self.mdays.get(k, {}).items():
                    per[mk] += c
            rows = [(k, v, per.get(k.rsplit("|", 1)[0], 0.0)) for k, v in self.models.items() if view == "all" or k.split("|")[0] == view]
            rows.sort(key=lambda r: (-r[2], -r[1][0]))
            total = sum(v[0] for _, v, _p in rows) or 1
            FN = "Microsoft YaHei UI"
            head = tk.Frame(self.mlist, bg=BG)
            head.pack(fill="x")
            tk.Label(head, text="模型", bg=BG, fg=MUT, font=(FN, fs(8)), anchor="w").pack(side="left")
            tk.Label(head, text="累计", bg=BG, fg=MUT, font=(FN, fs(8)), width=13, anchor="e").pack(side="right")
            tk.Label(head, text=plab, bg=BG, fg=MUT, font=(FN, fs(8)), width=9, anchor="e").pack(side="right")
            for key, (c, tok), pc in rows:
                _v, tool, model, flag = key.split("|")
                row = tk.Frame(self.mlist, bg=BG)
                row.pack(fill="x")
                tk.Label(row, text=f"{model[:24]}", bg=BG, fg=FG, font=(FN, fs(10)), anchor="w").pack(side="left")
                tk.Label(row, text=tool, bg=BG, fg=MUT, font=(FN, fs(8))).pack(side="left", padx=4)
                right = "无价格" if flag else f"{fm(c)} {c / total * 100:.0f}%"
                tk.Label(row, text=right, bg=BG, fg="#e0594b" if flag else MUT, font=(FN, fs(9)), width=13, anchor="e").pack(side="right")
                tk.Label(row, text=fm(pc) if pc else "—", bg=BG, fg=FG if pc else MUT, font=(FN, fs(10), "bold" if pc else "normal"), width=9, anchor="e").pack(side="right")
        self.root.update_idletasks()
        if self.embedded:
            if self.on_resize:
                self.on_resize()
        else:
            self.root.geometry(f"{self.W}x{self.root.winfo_reqheight() + int(6 * self.S)}")

    def quit(self):
        self.save()
        self.root.destroy()

    # ---- 数据
    def refresh(self):
        """重新读取数据;正在读取时忽略重复点击。"""
        if getattr(self, "busy", False):
            return
        self.busy = True
        self.status = "刷新中…"
        self.rbtn.config(fg=COLS[0], text="↻ 刷新中")
        self.foot.config(text=self.status)

        def work():
            try:
                r = collect()
                self.days, self.models, self.toks, self.extra = r["days"], r["models"], r["toks"], r["extra"]
                self.mdays = r.get("mdays", {})
                json.dump(r, open(CACHE, "w", encoding="utf-8"))
                self.status = f"更新于 {datetime.now():%H:%M:%S}"
            except Exception as ex:
                self.status = f"读取失败:{ex}"
            self.busy = False
            self.root.after(0, self.after_refresh)
        threading.Thread(target=work, daemon=True).start()

    def after_refresh(self):
        self.rbtn.config(fg=MUT, text="↻ 刷新")
        self.draw()

    def loop(self):
        self.refresh()
        self.root.after(300000, self.loop)

    def vendor_totals(self, v):
        """v 为厂商或 all:API 等值(含校准估算)、累计已付、回本倍数。"""
        vs = self.VKEYS if v == "all" else (v,)
        total = sum(self.day_total(d, v) for d in self.days.values()) + sum(self.extra.get(x, {}).get("cost", 0) for x in vs)
        paid = self.paid_total(v)
        return total, paid, (total / paid if paid else 0)

    def tokens_of(self, v):
        """某厂商(或 all)的 token 总量:本机记录 + GPT 校准差额。"""
        vs = self.VKEYS if v == "all" else (v,)
        return sum(d.get(x, 0) for d in self.toks.values() for x in vs) + sum(self.extra.get(x, {}).get("tokens", 0) for x in vs)

    def scope_stats(self, view):
        D = {k: self.day_total(v, view) for k, v in self.days.items()}
        today = datetime.now().date()
        ts = today.isoformat()
        t = D.get(ts, 0)
        mo = ts[:7]
        cur = sum(v for k, v in D.items() if k.startswith(mo))
        pms = (today.replace(day=1) - timedelta(1)).strftime("%Y-%m")
        prev = sum(v for k, v in D.items() if k.startswith(pms) and int(k[8:]) <= today.day)
        gran = self.cfg.get("gran", "day")
        monday = today - timedelta(today.weekday())
        wk = lambda m: sum(D.get((m + timedelta(j)).isoformat(), 0) for j in range(7))
        week, lastweek = wk(monday), wk(monday - timedelta(7))
        if gran == "week":      # 最近 12 周(周一到周日), 最后一根 = 本周
            series = [wk(monday - timedelta(7 * (11 - i))) for i in range(12)]
        elif gran == "month":   # 最近 12 个月, 最后一根 = 本月
            y, m = today.year, today.month
            keys = []
            for _ in range(12):
                keys.append(f"{y}-{m:02d}")
                y, m = (y - 1, 12) if m == 1 else (y, m - 1)
            series = [sum(v for k, v in D.items() if k.startswith(mk)) for mk in reversed(keys)]
        else:
            series = [D.get((today - timedelta(29 - i)).isoformat(), 0) for i in range(30)]
        self._wk = (week, lastweek, sum(D.get((today - timedelta(i)).isoformat(), 0) for i in range(30)) / 30)
        return t, cur, prev, series

    # ---- 绘制
    def rr(self, d, box, fill=None, outline=None, width=0, radius=12):
        K, S = self.K, self.S
        d.rounded_rectangle([v * K for v in box], radius=radius * S * K, fill=fill, outline=outline, width=int(width * K))

    # 版面(单位 = 1 个缩放像素): 总览卡 / 三张厂商卡 / 范围面板
    HERO_H, CY0, CY1, PY, PANEL_H = 108, 118, 214, 224, 208
    SEG_X, SEG_W = 150, 30
    EDGE, PILL = "#2e2d2a", "#3b3a36"

    def set_extra(self, units):
        self.grow = max(0, int(units))
        self.ch = int((440 + self.grow) * self.S)
        self.cv.config(height=self.ch)
        self.draw()

    def draw(self):
        c, S, cw, ch = self.cv, self.S, self.cw, self.ch
        c.delete("all")
        X = self.grow
        view = self.cfg["view"]
        gran = self.cfg.get("gran", "day")
        self.K = K = 3
        gap = 8 * S
        cardw = (cw - 2 * gap) / 3
        tot_all, paid_all, mult_all = self.vendor_totals("all")
        vt = {v: self.vendor_totals(v) for v in self.VKEYS}
        vcol = dict(zip(self.VKEYS, COLS))
        vcol["all"] = self.ACCENT
        scol = vcol[view]
        py = self.PY * S

        im = Image.new("RGB", (cw * K, ch * K), BG)
        d = ImageDraw.Draw(im)
        # 1) 总览卡 + 三家占比条
        self.rr(d, (0, 0, cw, self.HERO_H * S), fill=CARD, outline=self.EDGE, width=1, radius=16)
        bx0, bx1, by = 18 * S, cw - 18 * S, (self.HERO_H - 16) * S
        self.rr(d, (bx0, by, bx1, by + 6 * S), fill=TRACK, radius=3)
        x = bx0
        for v in self.VKEYS:
            share = vt[v][0] / tot_all if tot_all else 0
            wseg = (bx1 - bx0) * share
            if wseg >= 2 * S:
                self.rr(d, (x, by, x + wseg - 1.5 * S, by + 6 * S), fill=vcol[v] if view in ("all", v) else TRACK, radius=3)
            x += wseg
        # 2) 三张厂商卡
        for i, v in enumerate(self.VKEYS):
            x0 = i * (cardw + gap)
            sel = view == v
            self.rr(d, (x0, self.CY0 * S, x0 + cardw, self.CY1 * S), fill=CARD, outline=vcol[v] if sel else self.EDGE, width=2 if sel else 1, radius=14)
        # 3) 范围面板: 分段开关 + 柱状图 + 分隔线
        self.rr(d, (0, py, cw, py + (self.PANEL_H + X) * S), fill=CARD, outline=self.EDGE, width=1, radius=16)
        sx, sw = self.SEG_X * S, self.SEG_W * S
        self.rr(d, (sx, py + 11 * S, sx + 3 * sw, py + 33 * S), fill=TRACK, radius=11)
        gi = ("day", "week", "month").index(gran)
        self.rr(d, (sx + gi * sw + 2 * S, py + 13 * S, sx + (gi + 1) * sw - 2 * S, py + 31 * S), fill=self.PILL, radius=9)
        t, cur, prev, series = self.scope_stats(view)
        mx = max(series + [1e-9])
        cx0, cx1, cy0, cy1 = 18 * S, cw - 18 * S, py + 52 * S, py + (116 + X) * S
        n = len(series)
        bw = (cx1 - cx0) / n
        padb = 1 * S if n > 20 else 3 * S
        for i, val in enumerate(series):
            h = max(2 * S, (cy1 - cy0) * val / mx) if val > 0 else 2 * S
            col = scol if val > 0 else TRACK
            if i == n - 1 and val > 0:
                col = FG
            self.rr(d, (cx0 + i * bw + padb, cy1 - h, cx0 + (i + 1) * bw - padb, cy1), fill=col, radius=2 if n > 20 else 4)
        d.line([(18 * S * K, (py + (142 + X) * S) * K), ((cw - 18 * S) * K, (py + (142 + X) * S) * K)], fill=self.EDGE, width=max(1, int(K)))
        im = im.resize((cw, ch), Image.LANCZOS)
        self.img = ImageTk.PhotoImage(im)
        c.create_image(0, 0, image=self.img, anchor="nw")

        F = "Microsoft YaHei UI"
        # 总览卡文字: 永远是三家合计
        c.create_text(18 * S, 20 * S, text="总回本", anchor="w", fill=MUT, font=(F, fs(9)))
        c.create_text(16 * S, 52 * S, text=f"{mult_all:.1f}×", anchor="w", fill=FG, font=(FONT, fs(30), "bold"))
        c.create_text(18 * S, 80 * S, text="三家合计 · 累计 · 含估算", anchor="w", fill=MUT, font=(F, fs(7)))
        for i, (lab, val) in enumerate((("API 等值", fm(tot_all)), ("已付", fm(paid_all)), ("Token", ftok(self.tokens_of("all"))))):
            y = (22 + 22 * i) * S
            c.create_text(cw - 122 * S, y, text=lab, anchor="e", fill=MUT, font=(F, fs(9)))
            c.create_text(cw - 18 * S, y, text=val, anchor="e", fill=FG, font=(FONT, fs(12), "bold"))
        # 厂商卡文字
        for i, v in enumerate(self.VKEYS):
            x0 = i * (cardw + gap) + 14 * S
            tot, paid, mult = vt[v]
            on = view in ("all", v)
            y0 = self.CY0 * S
            c.create_oval(x0, y0 + 13 * S, x0 + 8 * S, y0 + 21 * S, fill=vcol[v], outline="")
            c.create_text(x0 + 14 * S, y0 + 17 * S, text=self.VNAMES[v], anchor="w", fill=FG if on else MUT, font=(F, fs(10), "bold"))
            share = vt[v][0] / tot_all * 100 if tot_all else 0
            c.create_text(i * (cardw + gap) + cardw - 12 * S, y0 + 17 * S, text=f"{share:.0f}%", anchor="e", fill=MUT, font=(FONT, fs(9)))
            c.create_text(x0 - 1 * S, y0 + 46 * S, text=f"{mult:.1f}×", anchor="w", fill=FG if on else MUT, font=(FONT, fs(19), "bold"))
            c.create_text(x0, y0 + 68 * S, text=f"{fm(tot)} / {fm(paid)}", anchor="w", fill=MUT, font=(F, fs(8)))
            c.create_text(x0, y0 + 83 * S, text=f"{ftok(self.tokens_of(v))} token", anchor="w", fill=MUT, font=(F, fs(8)))
        # 范围面板文字
        c.create_text(18 * S, py + 22 * S, text=self.VNAMES[view], anchor="w", fill=scol, font=(F, fs(11), "bold"))
        for i, (g, lab) in enumerate((("day", "日"), ("week", "周"), ("month", "月"))):
            c.create_text((self.SEG_X + self.SEG_W * (i + 0.5)) * S, py + 22 * S, text=lab, fill=FG if g == gran else MUT, font=(F, fs(9), "bold" if g == gran else "normal"))
        plan = self.plan_for(view)
        c.create_text(cw - 18 * S, py + 22 * S, text=f"套餐 ${plan:g}/月" + ("" if view == "all" else " ▾"), anchor="e", fill=MUT, font=(F, fs(9)))
        left, right = dict(day=("30 天前", "今天"), week=("12 周前", "本周"), month=("12 个月前", "本月"))[gran]
        c.create_text(18 * S, py + (128 + X) * S, text=left, anchor="w", fill=MUT, font=(F, fs(7)))
        c.create_text(cw - 18 * S, py + (128 + X) * S, text=right, anchor="e", fill=MUT, font=(F, fs(7)))
        tot, paid, mult = self.vendor_totals(view)
        week, lastweek, avg30 = self._wk
        cols = [("今日", fm(t), f"日均 {fm(avg30)}"),
                ("本周", fm(week), f"上周 {fm(lastweek)}"),
                ("本月", fm(cur), f"{cur / plan:.1f}× 月费" if plan else ""),
                ("累计", fm(tot), f"{ftok(self.tokens_of(view))} token")]
        hot = dict(day=0, week=1, month=2)[gran]
        nc = len(cols)
        for i, (lab, val, sub) in enumerate(cols):
            x = 18 * S + (cw - 36 * S) * (2 * i + 1) / (2 * nc)
            c.create_text(x, py + (158 + X) * S, text=lab, fill=scol if i == hot else MUT, font=(F, fs(8), "bold" if i == hot else "normal"))
            c.create_text(x, py + (176 + X) * S, text=val, fill=FG, font=(FONT, fs(12), "bold"))
            c.create_text(x, py + (193 + X) * S, text=sub, fill=MUT, font=(F, fs(7)))
        self.foot.config(text=self.status)
        self.draw_models()


if __name__ == "__main__":
    App().root.mainloop()
