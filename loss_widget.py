"""亏损统计(合并面板里单独一列): 读写 dashboard 亏损账本(模块 62, /api/loss-ledger)。
上面是总累计; 下面按项目分组, 每个项目一行累计亏损, 下面列出这个项目的每一笔。
「＋ 记一笔」直接在这里加(项目 + 金额, 日期默认今天), 写进同一本账, dashboard 里也能看到。每 60 秒刷新。"""
import os, threading, tkinter as tk, webbrowser
from collections import OrderedDict
import requests
from PIL import Image, ImageDraw, ImageTk

ZOOM = float(os.environ.get("SYK_ZOOM") or 1.0)
BG, CARD, FG, MUT, EDGE, ACC, FIELD = "#161615", "#222220", "#f3f2ee", "#8f8c84", "#2e2d2a", "#4c8dff", "#2b2a27"
LOSS, GAIN = "#e0594b", "#2fa36b"
FONT, F = "Segoe UI Variable Text", "Microsoft YaHei UI"
API = "http://127.0.0.1:8888/api/loss-ledger"
PAGE = "http://127.0.0.1:8888/portal?module=62"
TOP_H, GROUP_H, ITEM_H = 96, 30, 22


def fs(n):
    return max(6, round(n * ZOOM))


def money(v):
    return f"{v:,.0f}" if abs(v) >= 100 or v == int(v) else f"{v:,.2f}"


def session():
    s = requests.Session()
    s.trust_env = False          # 本机接口不走 7890 代理
    return s


class App:
    def __init__(self, master, on_resize=None, width=268):
        self.root = master.winfo_toplevel()
        self.on_resize = on_resize
        self.S = S = max(1.0, self.root.winfo_fpixels("1i") / 96) * ZOOM
        self.pad = int(14 * S)
        self.cw = int(width * S) - 2 * self.pad
        self.data, self.err, self.dirty, self.result = None, "", False, None
        self.list_h = 300                 # 明细卡片高度(缩放前单位), 合并面板会按三栏对齐重设

        bar = tk.Frame(master, bg=BG)
        bar.pack(fill="x", padx=self.pad, pady=(int(10 * S), 0))
        tk.Label(bar, text="亏损统计", bg=BG, fg=MUT, font=(F, fs(9))).pack(side="left")
        self.add_btn = tk.Label(bar, text="＋ 记一笔", bg=BG, fg=ACC, cursor="hand2", font=(F, fs(9)))
        self.add_btn.pack(side="right")
        self.add_btn.bind("<Button-1>", lambda e: self.toggle_form())

        # 记一笔的小表单, 默认收起
        self.form = tk.Frame(master, bg=BG)
        row = tk.Frame(self.form, bg=BG)
        row.pack(fill="x")
        self.e_name = self.entry(row, "项目 / 币", 10)
        self.e_amt = self.entry(row, "亏损 U", 8)
        ok = tk.Label(row, text="记", bg=ACC, fg="#ffffff", cursor="hand2", font=(F, fs(9), "bold"), padx=int(10 * S), pady=int(2 * S))
        ok.pack(side="right")
        ok.bind("<Button-1>", lambda e: self.submit())
        self.e_amt.bind("<Return>", lambda e: self.submit())
        self.e_name.bind("<Return>", lambda e: self.e_amt.focus_set())
        self.ok_btn = ok
        # 第二行: 日期 + (改已有记录时)删除 / 取消。20261013 用户:「亏损统计 我需要可编辑」——点下面任意一笔就进这里改
        row2 = tk.Frame(self.form, bg=BG)
        row2.pack(fill="x", pady=(int(5 * S), 0))
        self.e_date = self.entry(row2, "日期 10-05", 10)
        self.del_btn = tk.Label(row2, text="删除", bg=BG, fg=LOSS, cursor="hand2", font=(F, fs(9)))
        self.del_btn.bind("<Button-1>", lambda e: self.delete())
        self.cancel_btn = tk.Label(row2, text="取消", bg=BG, fg=MUT, cursor="hand2", font=(F, fs(9)))
        self.cancel_btn.bind("<Button-1>", lambda e: self.toggle_form())
        self.e_date.bind("<Return>", lambda e: self.submit())
        self.editing, self.del_armed, self.hits, self.more = None, False, [], False
        self.msg = tk.Label(self.form, text="回本填负数；日期默认今天", bg=BG, fg=MUT, font=(F, fs(8)), anchor="w")
        self.msg.pack(fill="x", pady=(int(4 * S), 0))

        self.top = tk.Canvas(master, width=self.cw, height=int(TOP_H * S), bg=BG, highlightthickness=0)
        self.top.pack(padx=self.pad, pady=(int(8 * S), 0))
        self.cv = tk.Canvas(master, width=self.cw, height=int(self.list_h * S), bg=BG, highlightthickness=0, cursor="hand2")
        self.cv.pack(padx=self.pad, pady=(int(8 * S), int(12 * S)))
        self.cv.bind("<Button-1>", self.click)
        self.paint()
        self.loop()
        self.tick()

    def entry(self, parent, hint, width):
        e = tk.Entry(parent, width=width, bg=FIELD, fg=MUT, insertbackground=FG, relief="flat", font=(F, fs(9)),
                     highlightthickness=1, highlightbackground=EDGE, highlightcolor=ACC)
        e.insert(0, hint)
        e.hint = hint

        def focus_in(_):
            if e.get() == e.hint:
                e.delete(0, "end")
                e.config(fg=FG)

        def focus_out(_):
            if not e.get():
                e.insert(0, e.hint)
                e.config(fg=MUT)
        e.bind("<FocusIn>", focus_in)
        e.bind("<FocusOut>", focus_out)
        e.pack(side="left", padx=(0, int(6 * self.S)), ipady=int(3 * self.S))
        return e

    def value(self, e):
        v = e.get().strip()
        return "" if v == e.hint else v

    def put(self, e, text):
        e.delete(0, "end")
        e.insert(0, text if text else e.hint)
        e.config(fg=FG if text else MUT)

    def set_mode(self, item):
        """item=None 是记新的一笔; 给一条记录就是改它(表单带上原来的项目 / 金额 / 日期, 多出删除和取消)。"""
        self.editing, self.del_armed = item, False
        self.del_btn.config(text="删除")
        for b in (self.del_btn, self.cancel_btn):
            b.pack_forget()
        if item:
            self.put(self.e_name, str(item.get("asset") or ""))
            self.put(self.e_amt, money(item.get("amount") or 0).replace(",", ""))
            self.put(self.e_date, str(item.get("date") or "")[5:])
            self.ok_btn.config(text="存")
            self.cancel_btn.pack(side="right")
            self.del_btn.pack(side="right", padx=(0, int(12 * self.S)))
            self.msg.config(text="改完点「存」；日期写 月-日", fg=MUT)
        else:
            for e in (self.e_name, self.e_amt, self.e_date):
                self.put(e, "")
            self.ok_btn.config(text="记")
            self.msg.config(text="回本填负数；日期不填就是今天", fg=MUT)

    def toggle_form(self, item=None):
        if self.form.winfo_ismapped() and not item:
            self.form.pack_forget()
            self.add_btn.config(text="＋ 记一笔")
            self.editing = None
        else:
            self.set_mode(item)
            if not self.form.winfo_ismapped():
                self.form.pack(fill="x", padx=self.pad, pady=(int(8 * self.S), 0), before=self.top)
            self.add_btn.config(text="收起")
            (self.e_amt if item else self.e_name).focus_set()
        if self.on_resize:
            self.on_resize()

    def click(self, e):
        """点某一笔 = 改这一笔; 点别处(项目标题、「还有 N 个项目」)= 打开 dashboard 的亏损账本。"""
        y = e.y / self.S
        for y0, y1, item in self.hits:
            if y0 <= y < y1:
                self.toggle_form(item)
                return
        if y > self.list_h - 6 - ITEM_H and self.more:      # 只有最下面那行「还有 N 个项目」才跳去网页
            webbrowser.open(PAGE)

    def full_date(self, text, old=""):
        """「10-05」→「2026-10-05」(年份沿用原记录的, 新记录用今年); 写了完整日期就原样用; 写错返回 None。"""
        import datetime
        text = text.strip().replace("/", "-").replace(".", "-")
        if not text:
            return old or ""
        parts = text.split("-")
        try:
            if len(parts) == 2:
                year = int(old[:4]) if old[:4].isdigit() else datetime.date.today().year
                return datetime.date(year, int(parts[0]), int(parts[1])).isoformat()
            if len(parts) == 3:
                return datetime.date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
        except ValueError:
            pass
        return None

    def post(self, body, done):
        def work():
            try:
                r = session().post(API, json=body, timeout=15).json()
                if r.get("ok") is False or "losses" not in r:
                    self.result = (False, r.get("msg") or r.get("error") or "没成功")
                else:
                    self.data, self.result = r, (True, done)
            except Exception:
                self.result = (False, "dashboard 没开，没成功")
            self.dirty = True
        threading.Thread(target=work, daemon=True).start()

    def submit(self):
        name = self.value(self.e_name)
        amt = self.value(self.e_amt).replace(",", "").replace("U", "").replace("u", "").strip()
        if not name or not amt:
            self.msg.config(text="项目和金额都要填", fg=LOSS)
            return
        item = self.editing
        day = self.full_date(self.value(self.e_date), str((item or {}).get("date") or ""))
        if day is None:
            self.msg.config(text="日期写成 月-日，比如 10-05", fg=LOSS)
            return
        self.msg.config(text="正在存…" if item else "正在记…", fg=MUT)
        if item:        # 改: 平台和备注不在这个小表单里, 原样带回去, 免得被清空
            self.post({"action": "update_loss", "id": item.get("id"), "asset": name, "amount": amt, "date": day,
                       "platform": item.get("platform") or "", "note": item.get("note") or ""}, f"已改：{name} {amt} U")
        else:
            self.post({"action": "add_loss", "asset": name, "amount": amt, "date": day}, f"已记：{name} {amt} U")

    def delete(self):
        item = self.editing
        if not item:
            return
        if not self.del_armed:      # 删除不能撤销, 要点两次
            self.del_armed = True
            self.del_btn.config(text="再点一次确认删除")
            return
        self.msg.config(text="正在删…", fg=MUT)
        self.post({"action": "delete_loss", "id": item.get("id")},
                  f"已删：{item.get('asset')} {money(item.get('amount') or 0)} U")

    def set_height(self, px):
        """合并面板给明细卡片的高度(像素)。"""
        self.list_h = max(120, px / self.S)
        self.cv.config(height=int(self.list_h * self.S))
        self.paint()

    def card(self, h):
        S, cw, K = self.S, self.cw, 3
        H = int(h * S)
        im = Image.new("RGB", (cw * K, H * K), BG)
        ImageDraw.Draw(im).rounded_rectangle([0, 0, cw * K - 1, H * K - 1], radius=16 * S * K, fill=CARD, outline=EDGE, width=K)
        return ImageTk.PhotoImage(im.resize((cw, H), Image.LANCZOS))

    def groups(self):
        """按项目分组: 每组 (项目名, 这个项目的累计, [每一笔, 新的在前]), 累计大的项目在前。"""
        g = OrderedDict()
        for x in (self.data or {}).get("losses") or []:
            g.setdefault(x.get("asset") or "未填", []).append(x)
        out = [(k, sum(i.get("amount") or 0 for i in v),
                sorted(v, key=lambda i: (i.get("date") or "", i.get("at") or 0), reverse=True)) for k, v in g.items()]
        return sorted(out, key=lambda t: -t[1])

    def paint(self):
        S, cw = self.S, self.cw
        t, c = self.top, self.cv
        t.delete("all")
        c.delete("all")
        self.top_img, self.list_img = self.card(TOP_H), self.card(self.list_h)
        t.create_image(0, 0, image=self.top_img, anchor="nw")
        c.create_image(0, 0, image=self.list_img, anchor="nw")
        if not self.data:
            t.create_text(14 * S, 48 * S, text=self.err or "读取中…", anchor="w", fill=MUT, font=(F, fs(9)))
            return
        sm = self.data.get("loss_summary") or {}
        groups = self.groups()
        total = sum(g[1] for g in groups)
        t.create_text(14 * S, 18 * S, text="累计亏损", anchor="w", fill=MUT, font=(F, fs(8)))
        t.create_text(14 * S, 48 * S, text=money(total), anchor="w", fill=LOSS if total >= 0 else GAIN, font=(FONT, fs(20), "bold"))
        t.create_text(cw - 14 * S, 52 * S, text="U", anchor="e", fill=MUT, font=(FONT, fs(10), "bold"))
        t.create_text(14 * S, 76 * S, text=f"本月 {money(sm.get('month_total') or 0)} U · {len(groups)} 个项目 · {sum(len(g[2]) for g in groups)} 笔",
                      anchor="w", fill=MUT, font=(F, fs(8)))

        if not groups:
            c.create_text(14 * S, 24 * S, text="还没有记录，点「＋ 记一笔」", anchor="w", fill=MUT, font=(F, fs(8)))
            return
        self.hits = []                      # 每一笔在卡片里的上下位置, 点击时用来认是哪一笔
        self.more = False
        y, bottom, shown, full = 6, self.list_h - 6, 0, True
        for gi, (name, sub, items) in enumerate(groups):
            reserve = ITEM_H if gi < len(groups) - 1 else 0      # 给「还有几个项目」留一行
            if y + GROUP_H > bottom - reserve:
                break
            if gi:
                c.create_line(14 * S, y * S, cw - 14 * S, y * S, fill=EDGE)
            cy = (y + GROUP_H / 2 + 1) * S
            c.create_text(14 * S, cy, text=name[:12], anchor="w", fill=FG, font=(F, fs(10), "bold"))
            c.create_text(cw - 14 * S, cy, text=money(sub), anchor="e", fill=LOSS if sub >= 0 else GAIN, font=(FONT, fs(11), "bold"))
            y += GROUP_H
            if len(items) == 1:
                # 这个项目只有一笔: 不再把同一个金额重复写一行; 整块(项目名那行 + 日期那行)点哪都是改这一笔。
                # 20261013 用户说「亏损那里还是不行」: 之前只有下面那行小字能点, 点粗体的项目名会跳去网页。
                x = items[0]
                if y + ITEM_H <= bottom - reserve:
                    iy = (y + ITEM_H / 2 - 2) * S
                    note = "旧总数导入" if x.get("legacy") else (x.get("platform") or x.get("note") or "")
                    c.create_text(14 * S, iy, text=(x.get("date") or "")[5:] + ("  " + note[:10] if note else ""), anchor="w",
                                  fill=MUT, font=(F, fs(8)))
                    c.create_text(cw - 14 * S, iy, text="改", anchor="e", fill=ACC, font=(F, fs(8)))
                    self.hits.append((y - GROUP_H, y + ITEM_H, x))
                    y += ITEM_H
                else:
                    self.hits.append((y - GROUP_H, y, x))
                y += 4
                shown = gi + 1
                continue
            for k, x in enumerate(items):
                if y + ITEM_H > bottom - reserve:
                    c.create_text(14 * S, (y + ITEM_H / 2 - 2) * S, text=f"…还有 {len(items) - k} 笔", anchor="w", fill=MUT, font=(F, fs(8)))
                    full = False
                    break
                iy = (y + ITEM_H / 2 - 2) * S
                note = "旧总数导入" if x.get("legacy") else (x.get("platform") or x.get("note") or "")
                c.create_text(14 * S, iy, text=(x.get("date") or "")[5:], anchor="w", fill=MUT, font=(FONT, fs(8)))
                c.create_text(54 * S, iy, text=note[:10], anchor="w", fill=MUT, font=(F, fs(8)))
                c.create_text(cw - 40 * S, iy, text=money(x.get("amount") or 0), anchor="e", fill=FG, font=(FONT, fs(9)))
                c.create_text(cw - 14 * S, iy, text="改", anchor="e", fill=ACC, font=(F, fs(8)))
                self.hits.append((y, y + ITEM_H, x))
                y += ITEM_H
            y += 4
            shown = gi + 1
            if not full:
                break
        if shown < len(groups):
            self.more = True
            c.create_text(14 * S, (bottom - ITEM_H / 2) * S, text=f"还有 {len(groups) - shown} 个项目，点这里看全部",
                          anchor="w", fill=ACC, font=(F, fs(8)))

    def loop(self):
        def work():
            try:
                self.data, self.err = session().get(API, timeout=15).json(), ""
            except Exception:
                self.err = "dashboard 没开，读不到账本" if not self.data else ""
            self.dirty = True             # 后台线程不碰界面, 由界面线程的 tick 来重画
        threading.Thread(target=work, daemon=True).start()
        self.root.after(60000, self.loop)

    def tick(self):
        if self.dirty:
            self.dirty = False
            if self.result:
                ok, text = self.result
                self.result = None
                self.msg.config(text=text, fg=GAIN if ok else LOSS)
                if ok:
                    self.set_mode(None)       # 存完 / 删完回到「记新的一笔」
                    self.msg.config(text=text, fg=GAIN)
            self.paint()
        self.root.after(500, self.tick)
