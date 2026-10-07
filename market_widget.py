"""行情栏: 美股三大指数 + BTC + 黄金, 每项带近 5 天走势小图。数据来自雅虎财经公开接口(走本机代理), 每 60 秒刷新。"""
import os, threading, time, tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import requests
from PIL import Image, ImageDraw, ImageTk

ZOOM = float(os.environ.get("SYK_ZOOM") or 1.0)
BG, CARD, FG, MUT, TRACK, EDGE = "#161615", "#222220", "#f3f2ee", "#8f8c84", "#34332f", "#2e2d2a"
UP, DOWN = "#2fa36b", "#e0594b"
FONT, F = "Segoe UI Variable Text", "Microsoft YaHei UI"
# Yahoo Finance is fetched through a local HTTP proxy by default; set SYK_PROXY="" to connect directly
_PROXY = os.environ.get("SYK_PROXY", "http://127.0.0.1:7890")
PX = {"http": _PROXY, "https": _PROXY} if _PROXY else None
# (显示名, 副标题, 雅虎代码候选(前一个取不到就试下一个), 小数位)
ITEMS = [("标普 500", "S&P 500", ["^GSPC"], 2), ("纳斯达克", "Nasdaq 综合", ["^IXIC"], 2), ("道琼斯", "Dow Jones", ["^DJI"], 2),
         ("BTC", "比特币 / 美元", ["BTC-USD"], 0), ("黄金", "美元 / 盎司", ["GC=F", "XAUUSD=X"], 2)]


def fs(n):
    return max(6, round(n * ZOOM))


def quote(symbols):
    for sym in symbols:
        for host in ("query1", "query2"):
            try:
                r = requests.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}", params={"interval": "30m", "range": "5d"},
                                 headers={"User-Agent": "Mozilla/5.0"}, proxies=PX, timeout=8)
                res = r.json()["chart"]["result"][0]
                m = res["meta"]
                px, prev = m.get("regularMarketPrice"), m.get("previousClose") or m.get("chartPreviousClose")
                closes = [v for v in (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or [] if v]
                if px:
                    # 涨跌按「上一交易日收盘」算; 5 天图的 chartPreviousClose 是 5 天前的, 不能用
                    day = requests.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}", params={"interval": "1d", "range": "5d"},
                                       headers={"User-Agent": "Mozilla/5.0"}, proxies=PX, timeout=8).json()["chart"]["result"][0]
                    dc = [v for v in day["indicators"]["quote"][0]["close"] if v]
                    base = dc[-2] if len(dc) >= 2 and abs(dc[-1] - px) / px < 0.02 else (dc[-1] if dc else prev)
                    return {"px": float(px), "chg": (px / base - 1) * 100 if base else None, "spark": closes[-120:]}
            except Exception:
                continue
    return None


class App:
    def __init__(self, master, on_resize=None, width=240):
        self.root = master.winfo_toplevel()
        self.on_resize = on_resize
        self.S = S = max(1.0, self.root.winfo_fpixels("1i") / 96) * ZOOM
        self.W = int(width * S)
        self.pad = int(14 * S)
        self.cw = self.W - 2 * self.pad      # 两侧留边和其他栏一致, 栏间距才相等
        self.data = [None] * len(ITEMS)
        self.stamp = "读取中…"
        self.ROW = 62
        bar = tk.Frame(master, bg=BG)
        bar.pack(fill="x", padx=self.pad, pady=(int(10 * S), 0))
        tk.Label(bar, text="行情", bg=BG, fg=MUT, font=(F, fs(9))).pack(side="left")
        self.tlab = tk.Label(bar, text="", bg=BG, fg=MUT, font=(F, fs(9)))
        self.tlab.pack(side="right")
        self.cv = tk.Canvas(master, width=self.cw, height=10, bg=BG, highlightthickness=0)
        self.cv.pack(padx=self.pad, pady=(int(8 * S), int(12 * S)))
        self.paint()
        self.loop()

    def set_height(self, px):
        """让卡片正好这么高(像素), 行高跟着变; 行够高时每项下面画走势小图。"""
        self.ROW = max(62, (px / self.S - 10) / len(ITEMS))
        self.paint()

    def paint(self):
        c, S, cw = self.cv, self.S, self.cw
        ch = int((self.ROW * len(ITEMS) + 10) * S)
        c.config(height=ch)
        c.delete("all")
        K = 3
        im = Image.new("RGB", (cw * K, ch * K), BG)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, cw * K - 1, ch * K - 1], radius=16 * S * K, fill=CARD, outline=EDGE, width=K)
        spark = self.ROW >= 88
        for i, q in enumerate(self.data):
            y0 = (5 + self.ROW * i) * S
            if i:
                d.line([(14 * S * K, y0 * K), ((cw - 14 * S) * K, y0 * K)], fill=EDGE, width=K)
            pts = (q or {}).get("spark") or []
            if spark and len(pts) >= 8:
                x0, x1, ya, yb = 14 * S, cw - 14 * S, y0 + 54 * S, y0 + (self.ROW - 12) * S
                lo, hi = min(pts), max(pts)
                rng = (hi - lo) or 1
                xy = [((x0 + (x1 - x0) * j / (len(pts) - 1)) * K, (yb - (yb - ya) * (v - lo) / rng) * K) for j, v in enumerate(pts)]
                # 走势是近 5 天的, 上面的涨跌是当天的, 两者方向可能相反, 所以线用中性色不用红绿
                d.line(xy, fill="#a9a69d", width=int(1.6 * S * K), joint="curve")
                ex, ey = xy[-1]
                r = 2.6 * S * K
                d.ellipse([ex - r, ey - r, ex + r, ey + r], fill=FG)
        self.img = ImageTk.PhotoImage(im.resize((cw, ch), Image.LANCZOS))
        c.create_image(0, 0, image=self.img, anchor="nw")
        for i, ((name, sub, _s, dec), q) in enumerate(zip(ITEMS, self.data)):
            y0 = (5 + self.ROW * i) * S
            c.create_text(14 * S, y0 + 19 * S, text=name, anchor="w", fill=FG, font=(F, fs(10), "bold"))
            c.create_text(14 * S, y0 + 38 * S, text=sub + (" · 近5天" if self.ROW >= 88 else ""), anchor="w", fill=MUT, font=(F, fs(7)))
            c.create_text(cw - 14 * S, y0 + 19 * S, text=f"{q['px']:,.{dec}f}" if q else "—", anchor="e", fill=FG, font=(FONT, fs(12), "bold"))
            if q and q["chg"] is not None:
                c.create_text(cw - 14 * S, y0 + 38 * S, text=f"{q['chg']:+.2f}%", anchor="e", fill=UP if q["chg"] >= 0 else DOWN, font=(FONT, fs(9), "bold"))
        self.tlab.config(text=self.stamp)

    def loop(self):
        def work():
            with ThreadPoolExecutor(len(ITEMS)) as ex:      # 五个一起取, 不排队
                got = list(ex.map(lambda it: quote(it[2]), ITEMS))
            for i, g in enumerate(got):                     # 没取到的隔 2 秒单独再试一次
                if not g:
                    time.sleep(2)
                    got[i] = quote(ITEMS[i][2])
            self.data = [g or old for g, old in zip(got, self.data)]     # 这次没取到就沿用上一次
            ok = sum(1 for g in got if g)
            self.stamp = f"{datetime.now():%H:%M}" + ("" if ok == len(ITEMS) else f" · {len(ITEMS) - ok} 项没取到")
            self.root.after(0, self.paint)
        threading.Thread(target=work, daemon=True).start()
        self.root.after(60000, self.loop)

    def btc(self):
        q = self.data[3]
        return q["px"] if q else None
