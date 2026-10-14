"""额度(合并面板里单独一列): 三个模型(Claude / GPT / Grok) + 付费 API, 一项一张卡片。
每张卡片只回答三件事: 还剩多少(大数字 + 粗条)、什么时候重置、现在正常不正常。没有官方剩余数的不编百分比, 大字写状态。
数据来自 dashboard 的额度中心(/api/quota/summary、/api/api-quota); Dune 的用量面板没有, 直接问 Dune 官方接口(一小时一次)。
每 2 分钟刷新。点卡片打开 dashboard 的额度中心。
20261013 第一版是「一行行列表」, 用户看了说「现在这个设计肯定不行」(剩 / 用 混着写、字挤出边、下面空一大片), 改成现在这样。"""
import os, re, threading, time, tkinter as tk, tkinter.font as tkfont, webbrowser
import requests
from PIL import Image, ImageDraw, ImageTk

ZOOM = float(os.environ.get("SYK_ZOOM") or 1.0)
BG, CARD, FG, MUT, EDGE, ACC, TRACK = "#161615", "#222220", "#f3f2ee", "#8f8c84", "#2e2d2a", "#4c8dff", "#34332f"
OK, WARN, BAD = "#2fa36b", "#d9a441", "#e0594b"
FONT, F = "Segoe UI Variable Text", "Microsoft YaHei UI"
DASH = "http://127.0.0.1:8888"
PAGE = DASH + "/api-quota"
# .env of the local dashboard that holds DUNE_API_KEY; SYK_DASHBOARD_ENV overrides the default location
ENV = os.environ.get("SYK_DASHBOARD_ENV") or os.path.join(os.path.expanduser("~"), "syk-dashboard", ".env")
HEAD_H, GAP, CARD_MIN, CARD_MAX = 24, 8, 72, 100
PAID = (("cmc", "CMC Pro"), ("coinank", "CoinAnk"))      # 额度中心里按月 / 按套餐付费的数据接口
STATE = {OK: "正常", WARN: "注意", BAD: "告急", MUT: "无数据"}


def fs(n):
    return max(6, round(n * ZOOM))


def num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"{v / 1e4:.1f} 万" if abs(v) >= 1e4 else f"{v:,.0f}"


def when(ts):
    """重置时间写成「周二 08:17」; 一周以外写日期。"""
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return ""
    lt = time.localtime(ts)
    if ts - time.time() > 7 * 86400:
        return time.strftime("%m-%d", lt)
    return "周" + "一二三四五六日"[lt.tm_wday] + time.strftime(" %H:%M", lt)


def level(left):
    """按剩余百分比定颜色。"""
    return BAD if left < 10 else WARN if left < 30 else OK


def session(proxy=False):
    s = requests.Session()
    s.trust_env = False              # 本机接口不走 7890 代理
    if proxy:
        s.proxies = {"https": "http://127.0.0.1:7890", "http": "http://127.0.0.1:7890"}
    return s


def dune_usage():
    """Dune 本期已用 / 套餐内 credits。面板没有这个数, 直接问官方; 失败返回 None(界面上不显示这张卡)。"""
    try:
        m = re.search(r"^\s*DUNE_API_KEY\s*=\s*[\"']?([^\"'\r\n]+)", open(ENV, encoding="utf-8", errors="replace").read(), re.M)
        if not m:
            return None
        r = session(proxy=True).post("https://api.dune.com/api/v1/usage", headers={"X-Dune-Api-Key": m.group(1).strip()},
                                     json={}, timeout=20).json()
        p = (r.get("billingPeriods") or r.get("billing_periods") or [{}])[0]
        used = p.get("creditsUsed", p.get("credits_used"))
        inc = p.get("creditsIncluded", p.get("credits_included"))
        if used is None or inc is None:
            return None
        return {"used": float(used), "limit": float(inc), "end": p.get("endDate") or p.get("end_date") or ""}
    except Exception:
        return None


CLAUDE_CRED = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
GROK_EST_LIMIT = 190        # 10-12 那一周用到约 188 次时被官方挡住, 只能拿这个当一周上限的估算


def iso_ts(text):
    """「2026-10-16T06:00:00.38+00:00」→ 秒级时间戳; 认不出返回 None。"""
    import datetime
    try:
        return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def claude_usage():
    """Claude 订阅的官方用量: 5 小时窗口和 7 天窗口各用了百分之几、什么时候重置。
    用本机 Claude Code 已有的登录去问 Anthropic 自己的接口(只读, 登录信息只发给 api.anthropic.com, 不打印不落盘);
    登录过期时不去刷新(那是 Claude Code 自己的事, 抢着刷会把它挤掉), 返回 {"expired": True}。失败返回 None。"""
    try:
        import json
        o = json.load(open(CLAUDE_CRED, encoding="utf-8")).get("claudeAiOauth") or {}
        if not o.get("accessToken"):
            return None
        r = session(proxy=True).get("https://api.anthropic.com/api/oauth/usage", timeout=20, headers={
            "Authorization": "Bearer " + o["accessToken"], "anthropic-beta": "oauth-2025-04-20", "User-Agent": "claude-code/2.0"})
        if r.status_code in (401, 403):
            return {"expired": True}
        d = r.json()
        out = {}
        for key, name in (("five_hour", "h5"), ("seven_day", "d7")):
            w = d.get(key) or {}
            if isinstance(w.get("utilization"), (int, float)):
                out[name] = {"used": float(w["utilization"]), "reset": iso_ts(w.get("resets_at"))}
        return out or None
    except Exception:
        return None


def build_rows(summary, quota, dune, claude=None):
    """整理成两组卡片: (模型, 付费 API)。每张 = dict(name, big, unit, right, sub, left, color)。
    big 是大字(有官方剩余数就是数字, 没有就是状态词); unit 是大字后面的小字; right 是右上角(重置 / 到期时间);
    left 是剩余百分比(画粗条用), 没有官方数就是 None, 不拿估算冒充。"""
    tools = {t.get("id"): t for t in (summary or {}).get("ai_tools") or []}
    apis = {a.get("id"): a for a in (quota or {}).get("apis") or []}
    models = []

    t = tools.get("claude") or {}
    row = {"name": "Claude", "big": "读不到", "unit": "", "right": "", "left": None, "color": MUT,
           "sub": f"后台调用今日 {num(t.get('today'))} 次"}
    if claude and claude.get("expired"):
        row.update(big="登录过期", state="等 Claude 自己刷新", sub="打开一次 Claude 就会恢复")
    elif claude and claude.get("d7"):
        left = max(0.0, 100 - claude["d7"]["used"])
        h5 = claude.get("h5")
        row.update(big=f"{left:.0f}%", unit="本周剩余", left=left, color=level(left),
                   right=(when(claude["d7"]["reset"]) + " 重置") if claude["d7"].get("reset") else "",
                   sub=(f"5 小时窗口剩 {max(0.0, 100 - h5['used']):.0f}%"
                        + (f" · {time.strftime('%H:%M', time.localtime(h5['reset']))} 重置" if h5.get("reset") else "")) if h5 else "")
        if h5 and h5["used"] >= 90:           # 周额度还有, 但眼下这 5 小时快用完了
            row.update(state="5 小时窗口快满", state_color=WARN)
    models.append(row)

    t = tools.get("openai-codex") or {}
    off = t.get("official") or {}
    left = off.get("value")
    row = {"name": "GPT", "big": "读不到", "unit": "", "right": "", "left": None, "color": MUT,
           "sub": f"今日 {num(t.get('today'))} 次 · 本周 {num(t.get('week'))} 次"}
    if isinstance(left, (int, float)):
        row.update(big=f"{left:.0f}%", unit="周额度剩余", left=float(left), color=level(left),
                   right=(when(off.get("reset_at")) + " 重置") if off.get("reset_at") else "")
    models.append(row)

    t, g = tools.get("xai") or {}, apis.get("grok") or {}
    alive = (t.get("live") or {}).get("ok")
    xw = g.get("xai_week") or {}
    hit = g.get("spending_limit_today") or 0
    calls = xw.get("calls", t.get("week"))
    row = {"name": "Grok", "left": None, "unit": "",
           "big": "可用" if alive else ("不可用" if alive is False else "未知"),
           "color": BAD if alive is False else OK if alive else MUT,
           "right": (when(xw.get("next_reset")) + " 重置") if xw.get("next_reset") else "周二 08:17 重置",
           "sub": f"重置后已用 {num(calls)} 次"}
    if alive is not False and isinstance(calls, (int, float)):
        # 官方不给百分比(只在 grok.com 设置页里有), 这里按「上周用到约 188 次被挡」估一个, 明说是估算
        left = max(0.0, 100 - calls / GROK_EST_LIMIT * 100)
        row.update(big=f"约 {left:.0f}%", unit="估算剩余", left=left, color=level(left),
                   sub=f"重置后已用 {num(calls)} 次 · 按一周约 {GROK_EST_LIMIT} 次估")
    if hit and alive:
        row.update(state=f"今天撞限额 {hit} 次", state_color=WARN)
    models.append(row)

    paid = []
    for key, name in PAID:
        a = apis.get(key)
        if not a:
            continue
        rate, limit = a.get("success_rate_24h"), a.get("limit_month")
        row = {"name": name, "right": "", "left": None}
        if limit and a.get("month") is not None:
            left = max(0.0, 100 - float(a["month"]) / float(limit) * 100)
            row.update(big=f"{left:.0f}%", unit="本月剩余", left=left, color=level(left),
                       sub=f"已用 {num(a['month'])} / {num(limit)}")
        else:
            row.update(big=num(a.get("today")), unit="次 · 今日", color=OK if a.get("status") == "ok" else WARN,
                       sub=f"本月 {num(a.get('month'))} 次")
        if isinstance(rate, (int, float)):
            if rate < 80:                    # 额度够但调不通: 大数字还是按额度上色, 右上角单独标红
                row.update(state=f"近 24h 成功率 {rate:.0f}%", state_color=BAD)
            else:
                row["sub"] += f" · 成功率 {rate:.0f}%"
        paid.append(row)

    d = tools.get("deepseek") or {}
    bal = (d.get("official") or {}).get("value")
    if isinstance(bal, (int, float)):
        paid.append({"name": "DeepSeek", "big": f"{bal:,.1f}", "unit": "元 · 余额", "right": "", "left": None,
                     "color": BAD if bal < 5 else WARN if bal < 15 else OK,
                     "sub": f"今日 {num(d.get('today'))} 次 · 本周 {num(d.get('week'))} 次"})
    elif d:
        paid.append({"name": "DeepSeek", "big": "读不到", "unit": "余额", "right": "", "left": None, "color": MUT,
                     "state": "余额接口这次没通", "sub": f"今日 {num(d.get('today'))} 次 · 本周 {num(d.get('week'))} 次"})
    return models, paid


class App:
    def __init__(self, master, on_resize=None, width=268):
        self.root = master.winfo_toplevel()
        self.on_resize = on_resize
        self.S = S = max(1.0, self.root.winfo_fpixels("1i") / 96) * ZOOM
        self.pad = int(14 * S)
        self.cw = int(width * S) - 2 * self.pad
        self.summary = self.quota = self.dune = self.claude = None
        self.claude_at = 0.0
        self.dune_at, self.err, self.dirty, self.at = 0.0, "", False, 0.0
        self.list_h = 560                 # 整列卡片区的高度(缩放前单位), 合并面板会按各栏对齐重设
        self.imgs = {}
        self.sub_font = tkfont.Font(family=F, size=fs(8))

        bar = tk.Frame(master, bg=BG)
        bar.pack(fill="x", padx=self.pad, pady=(int(10 * S), 0))
        tk.Label(bar, text="额度", bg=BG, fg=MUT, font=(F, fs(9))).pack(side="left")
        self.stamp = tk.Label(bar, text="", bg=BG, fg=MUT, font=(FONT, fs(8)))
        self.stamp.pack(side="right")
        self.cv = tk.Canvas(master, width=self.cw, height=int(self.list_h * S), bg=BG, highlightthickness=0, cursor="hand2")
        self.cv.pack(padx=self.pad, pady=(int(8 * S), int(12 * S)))
        self.cv.bind("<Button-1>", lambda e: webbrowser.open(PAGE))
        self.paint()
        self.loop()
        self.tick()

    def set_height(self, px):
        """合并面板给这一列卡片区的高度(像素)。"""
        self.list_h = max(240, px / self.S)
        self.cv.config(height=int(self.list_h * self.S))
        self.paint()

    def card(self, h):
        """一张圆角卡片的底图, 同样高度的只画一次。"""
        H = int(h * self.S)
        if H not in self.imgs:
            cw, K = self.cw, 3
            im = Image.new("RGB", (cw * K, H * K), BG)
            ImageDraw.Draw(im).rounded_rectangle([0, 0, cw * K - 1, H * K - 1], radius=14 * self.S * K, fill=CARD, outline=EDGE, width=K)
            self.imgs[H] = ImageTk.PhotoImage(im.resize((cw, H), Image.LANCZOS))
        return self.imgs[H]

    def clip(self, text, width):
        """小字太长就截断加省略号, 不让它伸出卡片。"""
        if self.sub_font.measure(text) <= width:
            return text
        while text and self.sub_font.measure(text + "…") > width:
            text = text[:-1]
        return text + "…"

    def draw_card(self, y, h, r):
        c, S, cw = self.cv, self.S, self.cw
        L, R = 14 * S, cw - 14 * S
        c.create_image(0, y * S, image=self.card(h), anchor="nw")
        col = r["color"]
        c.create_text(L, (y + 14) * S, text=r["name"], anchor="w", fill=FG, font=(F, fs(10), "bold"))
        # 右上角: 状态(小圆点 + 字)。默认跟着额度的颜色; 额度够但另有毛病(调不通、撞限额)时单独写出来
        scol = r.get("state_color") or col
        st = r.get("state") or STATE.get(scol, "")
        c.create_text(R, (y + 14) * S, text=st, anchor="e", fill=scol, font=self.sub_font)
        tw = self.sub_font.measure(st)
        c.create_oval(R - tw - 11 * S, (y + 11) * S, R - tw - 5 * S, (y + 17) * S, fill=scol, outline="")
        # 大字 + 后面的小字说明: 放在名字和底部小字正中间
        bottom = 34 if r["left"] is not None else 22
        mid = y + 27 + (h - 27 - bottom) / 2
        big = c.create_text(L, mid * S, text=r["big"], anchor="w", fill=FG if col == MUT else col, font=(FONT, fs(15), "bold"))
        bx = c.bbox(big)[2]
        if r.get("unit"):
            c.create_text(bx + 6 * S, (mid + 3) * S, text=r["unit"], anchor="w", fill=MUT, font=self.sub_font)
        if r.get("right"):
            c.create_text(R, (mid + 3) * S, text=r["right"], anchor="e", fill=MUT, font=self.sub_font)
        # 底部: 一行小字; 有官方剩余数的再加一条粗条(填的是剩余)
        bar_y = y + h - 8
        c.create_text(L, (y + h - (19 if r["left"] is not None else 14)) * S, text=self.clip(r["sub"], R - L), anchor="w",
                      fill=MUT, font=self.sub_font)
        if r["left"] is not None:
            w = max(3, int(4 * S))
            c.create_line(L, bar_y * S, R, bar_y * S, fill=TRACK, width=w, capstyle="round")
            c.create_line(L, bar_y * S, L + (R - L) * min(1.0, max(0.02, r["left"] / 100)), bar_y * S, fill=col, width=w, capstyle="round")

    def paint(self):
        c, S = self.cv, self.S
        c.delete("all")
        if not self.summary and not self.quota:
            c.create_image(0, 0, image=self.card(CARD_MIN), anchor="nw")
            c.create_text(14 * S, CARD_MIN / 2 * S, text=self.err or "读取中…", anchor="w", fill=MUT, font=(F, fs(9)))
            return
        models, paid = build_rows(self.summary, self.quota, self.dune, self.claude)
        groups = [(t, rows) for t, rows in (("模型", models), ("付费 API", paid)) if rows]
        n = sum(len(rows) for _, rows in groups)
        free = self.list_h - HEAD_H * len(groups) - GAP * n
        h = int(max(CARD_MIN, min(CARD_MAX, free / max(1, n))))      # 卡片等高, 尽量把这一列撑满
        y = 0
        for title, rows in groups:
            c.create_text(2 * S, (y + HEAD_H / 2) * S, text=title, anchor="w", fill=MUT, font=(F, fs(8)))
            y += HEAD_H
            for r in rows:
                if y + h > self.list_h:
                    break
                self.draw_card(y, h, r)
                y += h + GAP
        self.stamp.config(text=(time.strftime("%H:%M", time.localtime(self.at)) + " 更新") if self.at else "")

    def worst(self):
        """给托盘提示用: 有没有红色的项。返回名字列表。"""
        models, paid = build_rows(self.summary, self.quota, self.dune, self.claude)
        return [r["name"] for r in models + paid if r["color"] == BAD]

    def loop(self):
        def work():
            try:
                s = session()
                self.summary = s.get(DASH + "/api/quota/summary", timeout=30).json()
                self.quota = s.get(DASH + "/api/api-quota", timeout=30).json()
                self.err, self.at = "", time.time()
            except Exception:
                self.err = "dashboard 没开，读不到额度" if not self.summary else ""
            if time.time() - self.claude_at > 290:         # Claude 官方用量: 5 分钟问一次
                self.claude_at = time.time()
                c = claude_usage()
                if c:
                    self.claude = c
            self.dirty = True             # 后台线程不碰界面, 由界面线程的 tick 来重画
        threading.Thread(target=work, daemon=True).start()
        self.root.after(120000, self.loop)

    def tick(self):
        if self.dirty:
            self.dirty = False
            self.paint()
        self.root.after(500, self.tick)
