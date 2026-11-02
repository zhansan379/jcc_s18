# -*- coding: utf-8 -*-
"""
英雄标注工具（PyQt6）
=====================
把截图里裁出来的 3D 棋子一块块摆出来，人工点选对应的英雄，用于以后给 VLM 做
few-shot 检索 / 本地模板匹配。

数据落在 jcc_s18/data/hero_labels/：
    labels.json          标注记录（按裁剪图 sha1 去重，同一个棋子只标一次）
    crops/<sha1>.png     裁剪原件，直接可以当参考模板用

快捷键：
    空格 / Enter  跳到下一个未标注
    Backspace     清空当前
    ← →           上一个 / 下一个棋子
    Ctrl+F        搜索英雄名
"""
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QAction, QFont, QIcon, QPixmap, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QToolButton, QVBoxLayout, QWidget,
)

# ------------------------------------------------------------------ 路径
def _root():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parent.parent


ROOT = _root()
DATA = ROOT / "data"
ICON_DIR = DATA / "heroicons_s18"
LABEL_DIR = DATA / "hero_labels"
CROP_DIR = LABEL_DIR / "crops"
LABELS_JSON = LABEL_DIR / "labels.json"

sys.path.insert(0, str(ROOT / "core"))

DEFAULT_IMAGES = [
    r"D:\Download\00a5a489-ca7a-4216-bef0-81821a313981.png",
    r"D:\Download\browserDownload\ac4a917bdab44aed128e36e3f51c8701a08bfb4d.jpg",
]


def crop_key(pil):
    buf = io.BytesIO()
    pil.save(buf, "PNG")
    b = buf.getvalue()
    return hashlib.sha1(b).hexdigest(), b


def load_labels():
    if LABELS_JSON.exists():
        try:
            return json.loads(LABELS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": 1, "items": {}, "images": []}


def save_labels(d):
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    CROP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LABELS_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, LABELS_JSON)


# ------------------------------------------------------------------ 主窗口
class Labeler(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("金铲铲 S18 英雄标注")
        self.resize(1360, 900)

        self.db = load_labels()
        self.items = self.db.setdefault("items", {})
        self.images = []            # [path...]
        self.cur_img = -1
        self.units = []             # [{crop, key, box, star, area}]
        self.idx = 0
        self.hero_buttons = []      # [(name, QToolButton)]

        self._build_ui()
        self._load_hero_icons()
        self._open_defaults()

    # ---------------- UI
    def _build_ui(self):
        f = QFont("Microsoft YaHei", 10)
        self.setFont(f)

        central = QWidget()
        self.setCentralWidget(central)
        v = QVBoxLayout(central)
        v.setContentsMargins(10, 8, 10, 10)
        v.setSpacing(8)

        # ---- 顶部工具条
        bar = QHBoxLayout()
        self.btn_open = QPushButton("打开截图…")
        self.btn_open.clicked.connect(self.pick_images)
        bar.addWidget(self.btn_open)

        self.btn_prev_img = QPushButton("上一张")
        self.btn_prev_img.clicked.connect(lambda: self.goto_image(self.cur_img - 1))
        self.btn_next_img = QPushButton("下一张")
        self.btn_next_img.clicked.connect(lambda: self.goto_image(self.cur_img + 1))
        bar.addWidget(self.btn_prev_img)
        bar.addWidget(self.btn_next_img)

        self.lbl_img = QLabel("—")
        self.lbl_img.setStyleSheet("color:#9aa4b2;")
        bar.addWidget(self.lbl_img)
        bar.addStretch(1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索英雄名（Ctrl+F）")
        self.search.setFixedWidth(200)
        self.search.textChanged.connect(self.filter_heroes)
        bar.addWidget(self.search)

        self.lbl_prog = QLabel("")
        self.lbl_prog.setStyleSheet("font-weight:bold;color:#5bd67a;")
        bar.addWidget(self.lbl_prog)
        v.addLayout(bar)

        # ---- 主体：左预览 / 右英雄网格
        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.preview = QLabel("还没有载入截图")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(360, 420)
        self.preview.setStyleSheet(
            "background:#14161c;border:1px solid #2b3040;border-radius:8px;color:#8b93a3;")
        lv.addWidget(self.preview, 1)

        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet("color:#c9d2e0;font-size:13px;")
        self.lbl_info.setWordWrap(True)
        lv.addWidget(self.lbl_info)

        row = QHBoxLayout()
        self.btn_clear = QPushButton("清空此格 (Backspace)")
        self.btn_clear.clicked.connect(self.clear_current)
        self.btn_next = QPushButton("下一个未标注 (空格)")
        self.btn_next.clicked.connect(self.next_unlabeled)
        row.addWidget(self.btn_clear)
        row.addWidget(self.btn_next)
        lv.addLayout(row)

        self.lbl_assigned = QLabel("")
        self.lbl_assigned.setStyleSheet(
            "font-size:15px;font-weight:bold;color:#5bd67a;padding:4px;")
        lv.addWidget(self.lbl_assigned)

        left.setMaximumWidth(430)
        split.addWidget(left)

        # 右：英雄按钮网格
        self.hero_host = QWidget()
        self.hero_grid = QGridLayout(self.hero_host)
        self.hero_grid.setContentsMargins(6, 6, 6, 6)
        self.hero_grid.setSpacing(6)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.hero_host)
        sc.setStyleSheet("QScrollArea{border:1px solid #2b3040;border-radius:8px;}")
        split.addWidget(sc)
        split.setSizes([420, 940])
        v.addWidget(split, 1)

        # ---- 底部：本图所有棋子的缩略条（绿=已标注 灰=未标注）
        self.strip_host = QWidget()
        self.strip = QHBoxLayout(self.strip_host)
        self.strip.setContentsMargins(4, 4, 4, 4)
        self.strip.setSpacing(6)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFixedHeight(132)
        sa.setWidget(self.strip_host)
        sa.setStyleSheet("QScrollArea{border:1px solid #2b3040;border-radius:8px;}")
        v.addWidget(sa)

        # 快捷键
        for keys, slot in (("Space", self.next_unlabeled), ("Return", self.next_unlabeled),
                           ("Backspace", self.clear_current),
                           ("Left", lambda: self.goto_unit(self.idx - 1)),
                           ("Right", lambda: self.goto_unit(self.idx + 1)),
                           ("Ctrl+F", self.search.setFocus)):
            sc = QShortcut(QKeySequence(keys), self)
            sc.activated.connect(slot)

    def _load_hero_icons(self):
        names = []
        if ICON_DIR.is_dir():
            names = sorted(os.path.splitext(f)[0] for f in os.listdir(ICON_DIR)
                           if f.lower().endswith(".png"))
        cols = 7
        for i, n in enumerate(names):
            b = QToolButton()
            b.setText(n)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setIcon(QIcon(str(ICON_DIR / (n + ".png"))))
            b.setIconSize(QSize(58, 58))
            b.setFixedSize(92, 96)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet(
                "QToolButton{border:1px solid #2b3040;border-radius:6px;color:#c9d2e0;}"
                "QToolButton:hover{background:#232838;border-color:#4a90e2;}")
            b.clicked.connect(lambda _=False, nm=n: self.assign(nm))
            self.hero_grid.addWidget(b, i // cols, i % cols)
            self.hero_buttons.append((n, b))
        self.hero_grid.setRowStretch(len(names) // cols + 1, 1)
        if not names:
            self.hero_buttons = []

    # ---------------- 载入截图
    def _open_defaults(self):
        imgs = [p for p in DEFAULT_IMAGES if os.path.exists(p)]
        if imgs:
            self.images = imgs
            self.goto_image(0)

    def pick_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择对局截图", r"D:\Download",
            "图片 (*.png *.jpg *.jpeg *.bmp)")
        if not paths:
            return
        start = len(self.images)
        self.images.extend(p for p in paths if p not in self.images)
        if start == len(self.images):
            return
        self.goto_image(start)

    def goto_image(self, i):
        if not self.images:
            return
        i = max(0, min(i, len(self.images) - 1))
        if i == self.cur_img:
            return
        self.cur_img = i
        self.scan_image(self.images[i])

    def scan_image(self, path):
        try:
            from PIL import Image
            import board_units as B
            import hero_names as HN
        except Exception as e:
            QMessageBox.critical(self, "依赖缺失", "无法载入 core 模块：%s" % e)
            return
        self.lbl_img.setText("载入中…")
        QApplication.processEvents()
        img = Image.open(path).convert("RGB")
        units = B.extract(img)
        self.units = []
        for k, u in enumerate(units, 1):
            c = HN.crop_unit(img, u)
            if c is None:
                continue
            key, png = crop_key(c)
            self.units.append({"no": k, "crop": c, "png": png, "key": key,
                               "box": u["box"], "star": u.get("star"),
                               "area": u.get("area")})
        self.lbl_img.setText("%s（%d 个棋子）" % (os.path.basename(path), len(self.units)))
        self.idx = 0
        # 默认跳到第一个未标注
        for j, it in enumerate(self.units):
            if it["key"] not in self.items:
                self.idx = j
                break
        self.rebuild_strip()
        self.show_unit(self.idx)
        self.update_progress()

    # ---------------- 展示
    def show_unit(self, i):
        if not self.units:
            self.preview.setText("这张图里没找到棋子")
            self.lbl_info.setText("")
            return
        i = max(0, min(i, len(self.units) - 1))
        self.idx = i
        it = self.units[i]
        c = it["crop"]
        big = c.resize((c.width * 3, c.height * 3))
        pm = QPixmap()
        buf = io.BytesIO(); big.save(buf, "PNG")
        pm.loadFromData(buf.getvalue())
        self.preview.setPixmap(pm)

        rec = self.items.get(it["key"])
        cur = rec["name"] if rec else None
        self.lbl_info.setText(
            "第 %d/%d 个　%s　%d★　裁剪 %d×%d px\n裁剪 sha1: %s"
            % (i + 1, len(self.units),
               "棋盘" if it["area"] == "board" else "备战席",
               it["star"] or 0, c.width, c.height, it["key"][:12]))
        if cur:
            self.lbl_assigned.setText("当前标注：%s" % cur)
            self.lbl_assigned.setStyleSheet(
                "font-size:16px;font-weight:bold;color:#5bd67a;padding:4px;")
        else:
            self.lbl_assigned.setText("未标注")
            self.lbl_assigned.setStyleSheet(
                "font-size:16px;font-weight:bold;color:#e8b23a;padding:4px;")
        self.highlight_strip(i)

    def filter_heroes(self, text):
        t = text.strip()
        for n, b in self.hero_buttons:
            b.setVisible((not t) or (t in n))

    # ---------------- 标注
    def assign(self, name):
        if not self.units:
            return
        it = self.units[self.idx]
        self.items[it["key"]] = {
            "name": name, "image": os.path.basename(self.images[self.cur_img]),
            "unit": it["no"], "star": it["star"], "area": it["area"],
            "box": it["box"], "crop": "crops/%s.png" % it["key"],
            "ts": int(time.time()),
        }
        CROP_DIR.mkdir(parents=True, exist_ok=True)
        p = CROP_DIR / (it["key"] + ".png")
        if not p.exists():
            p.write_bytes(it["png"])
        save_labels(self.db)
        self.rebuild_strip()
        self.show_unit(self.idx)
        self.update_progress()
        QTimer.singleShot(80, self.next_unlabeled)

    def clear_current(self):
        if not self.units:
            return
        it = self.units[self.idx]
        if it["key"] in self.items:
            del self.items[it["key"]]
            save_labels(self.db)
            self.rebuild_strip()
            self.show_unit(self.idx)
            self.update_progress()

    def next_unlabeled(self):
        if not self.units:
            return
        n = len(self.units)
        for d in range(1, n + 1):
            j = (self.idx + d) % n
            if self.units[j]["key"] not in self.items:
                self.show_unit(j)
                return
        self.lbl_assigned.setText("本图已全部标注完 ✔")
        self.lbl_assigned.setStyleSheet(
            "font-size:16px;font-weight:bold;color:#5bd67a;padding:4px;")

    def goto_unit(self, i):
        if self.units:
            self.show_unit(i)

    # ---------------- 底部缩略条
    def rebuild_strip(self):
        while self.strip.count():
            w = self.strip.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i, it in enumerate(self.units):
            rec = self.items.get(it["key"])
            name = rec["name"] if rec else None
            b = QToolButton()
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setIcon(QIcon(str(ICON_DIR / (name + ".png"))) if name and
                      (ICON_DIR / (name + ".png")).exists() else QIcon())
            pm = QPixmap(); pm.loadFromData(it["png"])
            b.setIcon(QIcon(pm))
            b.setIconSize(QSize(64, 64))
            b.setFixedSize(86, 116)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            col = "#5bd67a" if name else "#555b6b"
            b.setStyleSheet(
                "QToolButton{border:2px solid %s;border-radius:6px;color:#dbe3ef;"
                "background:%s;}" % (col, "#1b2230" if name else "#15171d"))
            b.setText("#%d %s" % (it["no"], name or "未标注"))
            b.clicked.connect(lambda _=False, j=i: self.show_unit(j))
            self.strip.addWidget(b)
        self.strip.addStretch(1)

    def highlight_strip(self, idx):
        for i in range(self.strip.count()):
            w = self.strip.itemAt(i).widget()
            if not isinstance(w, QToolButton):
                continue
            it = self.units[i] if i < len(self.units) else None
            if it is None:
                continue
            name = (self.items.get(it["key"]) or {}).get("name")
            if i == idx:
                w.setStyleSheet(
                    "QToolButton{border:2px solid #4a90e2;border-radius:6px;"
                    "color:#ffffff;background:#1f2a3d;}")
            else:
                col = "#5bd67a" if name else "#555b6b"
                w.setStyleSheet(
                    "QToolButton{border:2px solid %s;border-radius:6px;color:#dbe3ef;"
                    "background:%s;}" % (col, "#1b2230" if name else "#15171d"))

    def update_progress(self):
        n = len(self.units)
        done = sum(1 for it in self.units if it["key"] in self.items)
        self.lbl_prog.setText("本图 %d/%d　·　累计 %d 个不同棋子"
                              % (done, n, len(self.items)))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("金铲铲S18英雄标注")
    w = Labeler()
    w.show()
    if "--shot" in sys.argv:
        out = sys.argv[sys.argv.index("--shot") + 1]
        QTimer.singleShot(900, lambda: (w.grab().save(out), app.quit()))
        app.exec()
        print("saved", out)
        return
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
