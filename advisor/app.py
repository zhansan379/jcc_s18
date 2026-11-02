# -*- coding: utf-8 -*-
"""
金铲铲 S18 对局助手（PyQt6）
============================
固定工作流：打开截图 → 识别（OCR/CV）→ 规则推荐 → LLM 教练 → 双标签页展示

  Tab1「阵容推荐」  类似 dataj 阵容页：主推阵容 / 站位 / 变阵过渡 / 强化符文 /
                    装备合成 / 拿牌 / 节奏，外加一段 LLM 教练建议
  Tab2「识别标注」  原图上叠加每个识别结果的框与取值，右侧是可点选的结果表

设计约束：整条链路 ≤10s（实测 3.5~5s，缓存命中 <0.1s）。
  * 模型/静态数据在启动时就后台预热（约 2.4s，与用户选图并行）
  * LLM 硬超时 5s，失败立刻回落规则文案，绝不阻塞界面
  * 同一张图按内容哈希缓存，重复打开瞬间出结果

用法：
    python advisor/app.py                 # 打开界面
    python advisor/app.py 图.png           # 带图启动
    python advisor/app.py --shot out.png   # 自检：渲染两个标签页截图后退出
"""
import hashlib
import json
import math
import os
import sys
import time

from PyQt6.QtCore import (QPoint, QPointF, QRectF, QSize, Qt, QThread, QTimer,
                          pyqtSignal)
from PyQt6.QtGui import (QColor, QFont, QFontMetrics, QIcon, QImage, QPainter,
                         QPainterPath, QPen, QPixmap, QBrush)
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
                             QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QMainWindow, QMessageBox, QPushButton, QScrollArea,
                             QSizePolicy, QSplitter, QTabWidget,
                             QToolButton, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, ROOT)

import databook                                            # noqa: E402
import plan as plan_mod                                    # noqa: E402
import pipeline                                            # noqa: E402

OUT_CACHE = os.path.join(ROOT, "output", "advisor_cache")
DEFAULT_IMAGE = r"D:\Download\00a5a489-ca7a-4216-bef0-81821a313981.png"

# ------------------------------------------------------------------ 配色
BG = "#0e1015"
PANEL = "#151922"
CARD = "#1a1f2a"
LINE = "#2a3140"
TX = "#dde4f0"
MUTED = "#8b93a3"
ACC = "#4a90e2"
OK_C = "#5bd67a"
WARN_C = "#e8b23a"
BAD_C = "#e2604a"

TIER_C = {"S": "#ff6b6b", "A": "#c89bf5", "B": "#5bd67a", "C": "#7fb3ff", "D": "#8b93a3"}
GROUP_C = {
    "文本": "#4a90e2", "商店": "#4fd1c5", "单位": "#5bd67a", "羁绊": "#c89bf5",
    "装备栏": "#e8b23a", "强化符文": "#ff8fb1", "玩家": "#7fb3ff",
}
COST_C = {1: "#9aa4b2", 2: "#5bd67a", 3: "#4a9fe2", 4: "#c89bf5", 5: "#e8b23a"}
ROLE_C = {"主C": "#ff7a5c", "副C": "#5fa8f5", "主坦": "#5bd67a"}

_pm_cache = {}


def pixmap(path, size):
    """带缓存的图标加载；path 为空返回 None"""
    if not path or not os.path.exists(path):
        return None
    key = (path, size)
    if key in _pm_cache:
        return _pm_cache[key]
    pm = QPixmap(path)
    if pm.isNull():
        return None
    pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                   Qt.TransformationMode.SmoothTransformation)
    _pm_cache[key] = pm
    return pm


def icon_label(path, size, fallback=None):
    lb = QLabel()
    lb.setFixedSize(size, size)
    lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    pm = pixmap(path, size)
    if pm:
        lb.setPixmap(pm)
    else:
        ch = (fallback or "?")[:1]
        lb.setText(ch)
        lb.setStyleSheet("color:#c9d2e0;background:#232a38;border:1px solid %s;"
                         "border-radius:6px;font-size:%dpx;" % (LINE, max(10, size // 2)))
    return lb


def chip(text, color=ACC, bg=None, bold=False, size=12):
    lb = QLabel(text)
    lb.setStyleSheet(
        "QLabel{color:%s;background:%s;border:1px solid %s;border-radius:9px;"
        "padding:2px 9px;font-size:%dpx;%s}"
        % (color, bg or "rgba(255,255,255,0.04)", color, size,
           "font-weight:bold;" if bold else ""))
    return lb


def label(text, color=TX, size=13, bold=False, wrap=True):
    lb = QLabel(text)
    lb.setWordWrap(wrap)
    lb.setStyleSheet("color:%s;font-size:%dpx;%s" % (color, size,
                                                    "font-weight:bold;" if bold else ""))
    return lb


# ------------------------------------------------------------------ 站位棋盘
class HexBoard(QWidget):
    """4 行 × 7 列六边形站位表，row 0 是前排

    每格三行：头像 / 名字+星级 / 推荐装备（核心装描金边）。
    六边形上下两端是尖的，所以格子的高度要留够，让装备落在最宽的那一段。
    """

    ROWS, COLS = 4, 7
    PITCH = 0.94          # 行距 / 格高

    def __init__(self, parent=None):
        super().__init__(parent)
        self.units = []
        self.setFixedHeight(356)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_units(self, units):
        self.units = units or []
        self.update()

    def _cell(self):
        w = max(360, self.width() - 40)
        by_w = w / (self.COLS + 0.5)
        by_h = max(240, self.height() - 22) / (self.ROWS * self.PITCH)
        c = max(56.0, min(96.0, by_w, by_h))
        return c, c

    def _hex(self, cx, cy, cw, ch):
        rx, ry = cw * 0.58, ch * 0.52
        p = QPainterPath()
        for i in range(6):
            a = math.radians(60 * i + 30)
            x, y = cx + rx * math.cos(a), cy + ry * math.sin(a)
            if i == 0:
                p.moveTo(x, y)
            else:
                p.lineTo(x, y)
        p.closeSubpath()
        return p

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cw, ch = self._cell()
        left = 34
        x0 = left + (self.width() - left - self.COLS * cw) / 2 + cw / 2
        y0 = 18 + ch / 2
        pitch = ch * self.PITCH
        self._cells = {}

        f_small = QFont("Microsoft YaHei UI", 8)
        p.setFont(f_small)
        for r in range(self.ROWS):
            p.setPen(QPen(QColor(MUTED)))
            p.drawText(QRectF(2, y0 + r * pitch - 9, 30, 18),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       "前排" if r == 0 else ("后排" if r == self.ROWS - 1 else "第%d排" % (r + 1)))
            for c in range(self.COLS):
                cx = x0 + c * cw + (cw * 0.25 if r % 2 else 0)
                cy = y0 + r * pitch
                path = self._hex(cx, cy, cw, ch)
                p.setPen(QPen(QColor(LINE), 1))
                p.setBrush(QBrush(QColor("#11151d" if (r + c) % 2 else "#161c27")))
                p.drawPath(path)
                self._cells[(r, c)] = (cx, cy, cw, ch, path)

        for u in self.units:
            cell = self._cells.get((u.get("row"), u.get("col")))
            if cell:
                self._draw_unit(p, cell, u)

    def _draw_unit(self, p, cell, u):
        cx, cy, cw, ch, path = cell
        own = u.get("owned")
        edge = QColor(OK_C if own else (BAD_C if u.get("isMain") else "#5a6478"))
        p.setPen(QPen(edge, 2.4 if own else 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        name = u.get("name") or ""
        # 头像（贴着上半部）
        size = int(ch * 0.30)
        pm = pixmap(databook.icon_hero(name), size)
        if pm:
            p.save()
            p.setClipPath(path)
            p.drawPixmap(QPointF(cx - pm.width() / 2, cy - ch * 0.40), pm)
            p.restore()

        # 名字 + 星级（角色用颜色区分）
        f = QFont("Microsoft YaHei UI", 7)
        p.setFont(f)
        role = u.get("role")
        cap = ((role + "·") if role else "") + name + ("★%d" % u["stars"] if u.get("stars") else "")
        tw = QFontMetrics(f).horizontalAdvance(cap)
        cap_y = cy - ch * 0.02
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(10, 12, 16, 225)))
        p.drawRoundedRect(QRectF(cx - tw / 2 - 4, cap_y - 1, tw + 8, 13), 3, 3)
        col = ROLE_C.get(role) or (OK_C if own else "#c9d2e0")
        p.setPen(QPen(QColor(col)))
        p.drawText(QRectF(cx - tw / 2, cap_y, tw, 13),
                   Qt.AlignmentFlag.AlignCenter, cap)

        # 推荐装备（核心装描金边）
        equips = [e for e in (u.get("equips") or []) if e][:3]
        if equips:
            sz = int(ch * 0.20)
            gap = 2
            total = len(equips) * (sz + gap) - gap
            ex = cx - total / 2.0
            ey = cy + ch * 0.16
            for i, it in enumerate(equips):
                bx = ex + i * (sz + gap)
                ipm = pixmap(databook.icon_item(it), sz)
                if ipm:
                    p.drawPixmap(QPointF(bx, ey), ipm)
                if it == u.get("equip_core"):
                    p.setPen(QPen(QColor("#f0c15a"), 1.6))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(QRectF(bx - 1.5, ey - 1.5, sz + 3, sz + 3))

    def _unit_at(self, pos):
        for key, (cx, cy, cw, ch, _) in getattr(self, "_cells", {}).items():
            if abs(pos.x() - cx) <= cw * 0.5 and abs(pos.y() - cy) <= ch * 0.5:
                for u in self.units:
                    if (u.get("row"), u.get("col")) == key:
                        return u
        return None

    def mouseMoveEvent(self, ev):
        u = self._unit_at(ev.position())
        if not u:
            self.setToolTip("")
            return
        eq = [e for e in (u.get("equips") or []) if e]
        lines = ["%s%s" % (u.get("name"), ("★%d" % u["stars"]) if u.get("stars") else "")]
        if eq:
            lines.append("装备：" + "、".join(eq))
        elif u.get("cost"):
            lines.append("%d 费 · 没有指定装备" % u["cost"])
        self.setToolTip("\n".join(lines))

    def sizeHint(self):
        return QSize(620, 356)


# ------------------------------------------------------------------ 标注视图
class AnnotationView(QWidget):
    """原图 + 识别框；滚轮缩放、拖拽平移、点击选中"""
    clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.img = None
        self.items = []
        self.selected = None
        self.zoom = 1.0
        self.offset = QPointF(0, 0)
        self._drag = None
        self.groups = set()
        self.show_labels = True
        self.setMouseTracking(True)
        self.setMinimumSize(520, 380)
        self.setStyleSheet("background:%s;" % "#0b0d12")

    def set_image(self, path):
        self.img = QPixmap(path)
        self.zoom = 1.0
        self.offset = QPointF(0, 0)
        self.update()

    def set_items(self, items):
        self.items = items or []
        if not self.groups:
            self.groups = {it["group"] for it in self.items}
        self.update()

    def set_groups(self, groups):
        self.groups = set(groups)
        self.update()

    def set_show_labels(self, on):
        self.show_labels = bool(on)
        self.update()

    def _visible(self):
        return [it for it in self.items if it["group"] in self.groups]

    def select(self, item_id):
        self.selected = item_id
        self.update()

    def _fit_scale(self):
        if not self.img:
            return 1.0
        return min(self.width() / self.img.width(), self.height() / self.img.height())

    def _to_screen(self, x, y):
        s = self._fit_scale() * self.zoom
        cx = self.width() / 2 + self.offset.x()
        cy = self.height() / 2 + self.offset.y()
        return cx + (x - self.img.width() / 2) * s, cy + (y - self.img.height() / 2) * s, s

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#0b0d12"))
        if not self.img or self.img.isNull():
            p.setPen(QColor(MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "还没有载入截图")
            return

        s = self._fit_scale() * self.zoom
        w, h = self.img.width() * s, self.img.height() * s
        cx = self.width() / 2 + self.offset.x()
        cy = self.height() / 2 + self.offset.y()
        p.drawPixmap(QRectF(cx - w / 2, cy - h / 2, w, h), self.img,
                     QRectF(0, 0, self.img.width(), self.img.height()))

        f = QFont("Microsoft YaHei UI", 8)
        p.setFont(f)
        fm = QFontMetrics(f)
        for it in self._visible():
            x0, y0, x1, y1 = it["box"]
            sx0, sy0, _ = self._to_screen(x0, y0)
            sx1, sy1, _ = self._to_screen(x1, y1)
            col = QColor(GROUP_C.get(it["group"], ACC))
            sel = it["id"] == self.selected
            if sel:
                col = QColor("#ffffff")
            # 先描一圈深色底，浅色场景下框也能看清
            p.setPen(QPen(QColor(0, 0, 0, 150), 4.5 if sel else 3.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            rect = QRectF(sx0, sy0, max(2.0, sx1 - sx0), max(2.0, sy1 - sy0))
            p.drawRect(rect)
            p.setPen(QPen(col, 2.6 if sel else 1.7))
            p.drawRect(rect)

            if self.show_labels or sel:
                txt = it["label"]
                tw = fm.horizontalAdvance(txt) + 10
                ty = sy0 - 15 if sy0 - 15 > 2 else sy1 + 1
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(col.red(), col.green(), col.blue(),
                                         245 if sel else 215)))
                p.drawRoundedRect(QRectF(sx0, ty, tw, 15), 3, 3)
                p.setPen(QPen(QColor("#0b0d12")))
                p.drawText(QRectF(sx0 + 5, ty, tw, 15),
                           Qt.AlignmentFlag.AlignVCenter, txt)

    def wheelEvent(self, ev):
        if not self.img:
            return
        old = self._fit_scale() * self.zoom
        pos = ev.position()
        before = self._offset_to_img(pos, old)
        delta = 1.18 if ev.angleDelta().y() > 0 else 1 / 1.18
        self.zoom = max(1.0, min(6.0, self.zoom * delta))
        new = self._fit_scale() * self.zoom
        after = self._offset_to_img(pos, new)
        self.offset += QPointF((after.x() - before.x()) * new, (after.y() - before.y()) * new)
        self.update()

    def _offset_to_img(self, pos, scale):
        cx = self.width() / 2 + self.offset.x()
        cy = self.height() / 2 + self.offset.y()
        return QPointF((pos.x() - cx) / scale + self.img.width() / 2,
                       (pos.y() - cy) / scale + self.img.height() / 2)

    def mousePressEvent(self, ev):
        self._drag = (ev.position(), QPointF(self.offset))
        hit = self._hit(ev.position())
        if hit:
            self.selected = hit["id"]
            self.clicked.emit(hit["id"])
            self.update()

    def mouseMoveEvent(self, ev):
        if self._drag and ev.buttons() & Qt.MouseButton.LeftButton:
            d = ev.position() - self._drag[0]
            self.offset = self._drag[1] + d
            self.update()
        else:
            hit = self._hit(ev.position())
            self.setToolTip("%s\n%s" % (hit["label"], hit["value"]) if hit else "")

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def mouseDoubleClickEvent(self, ev):
        self.zoom = 1.0
        self.offset = QPointF(0, 0)
        self.update()

    def _hit(self, pos):
        if not self.img:
            return None
        for it in reversed(self._visible()):
            x0, y0, x1, y1 = it["box"]
            sx0, sy0, _ = self._to_screen(x0, y0)
            sx1, sy1, _ = self._to_screen(x1, y1)
            if QRectF(sx0, sy0, max(2, sx1 - sx0), max(2, sy1 - sy0)).contains(pos):
                return it
        return None


# ------------------------------------------------------------------ 工作线程
class Worker(QThread):
    done = pyqtSignal(object)
    progress = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs

    def run(self):
        try:
            self.done.emit(self.fn(*self.args, progress=self.progress.emit, **self.kwargs))
        except Exception as e:
            self.done.emit({"ok": False, "error": "%s: %s" % (type(e).__name__, e)})


# ------------------------------------------------------------------ Tab1
class Section(QWidget):
    """标题 + 富文本正文；左侧一条主色竖线，不用卡片边框"""

    def __init__(self, head, accent=ACC, emphasis=False, parent=None):
        super().__init__(parent)
        self.setObjectName("Emph" if emphasis else "Plain")
        if emphasis:
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.setStyleSheet(
                "QWidget#Emph{background:#1e2739;border:1px solid #55709f;border-radius:10px;}")
        v = QVBoxLayout(self)
        v.setContentsMargins(14 if emphasis else 0, 12 if emphasis else 0,
                             14 if emphasis else 0, 12 if emphasis else 0)
        v.setSpacing(6)
        headrow = QHBoxLayout()
        headrow.setSpacing(8)
        bar = QFrame()
        bar.setFixedSize(3, 15)
        bar.setStyleSheet("background:%s;border-radius:2px;" % accent)
        headrow.addWidget(bar)
        t = QLabel(head)
        t.setStyleSheet("color:%s;font-size:13px;font-weight:bold;" % accent)
        headrow.addWidget(t)
        headrow.addStretch(1)
        self.head = t
        v.addLayout(headrow)
        self.body = QLabel()
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setWordWrap(True)
        self.body.setStyleSheet("color:%s;font-size:13px;" % TX)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.body)

    def set_html(self, txt):
        self.body.setText('<div style="line-height:170%%">%s</div>' % txt)


class Fold(QWidget):
    """可以收起的一块（站位 / 数据来源）"""

    def __init__(self, title, state, key, parent=None):
        super().__init__(parent)
        self._key = key
        self._state = state
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.btn = QToolButton()
        self.btn.setText(title)
        self.btn.setCheckable(True)
        self.btn.setChecked(not state.get(key, False))
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn.setArrowType(Qt.ArrowType.NoArrow)
        self.btn.setStyleSheet(
            "QToolButton{color:%s;border:0;font-size:12px;padding:2px 0;}"
            "QToolButton:hover{color:%s;}" % (MUTED, TX))
        v.addWidget(self.btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.host = QWidget()
        self.body = QVBoxLayout(self.host)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(6)
        v.addWidget(self.host)
        self.btn.toggled.connect(self._on)
        self._on(self.btn.isChecked())

    def _on(self, on):
        self.host.setVisible(on)
        self._state[self._key] = not on
        self.btn.setText(("▾ " if on else "▸ ") + self.btn.text().lstrip("▾▸ "))


class RecommendTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self.sel = 0
        self.collapsed = {"board": True, "footer": True}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea{border:0;}")
        self.host = QWidget()
        self.v = QVBoxLayout(self.host)
        self.v.setContentsMargins(24, 16, 24, 24)
        self.v.setSpacing(16)
        self.scroll.setWidget(self.host)
        outer.addWidget(self.scroll)
        self.show_empty()

    # ---------------------------------------------------------- 骨架
    def _clear(self):
        def wipe(lay):
            while lay.count():
                it = lay.takeAt(0)
                w = it.widget()
                sub = it.layout()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
                elif sub is not None:
                    wipe(sub)
        wipe(self.v)

    def show_empty(self):
        self._clear()
        s = Section("等待截图")
        s.set_html("点左上角「打开截图」，或把图片直接拖进窗口。<br>"
                   "识别 → 规则推荐 → 教练建议，约 4 秒。")
        self.v.addWidget(s)
        self.v.addStretch(1)

    def render(self, res):
        self.result = res
        self.sel = 0
        self.repaint_all(top=True)

    def repaint_all(self, top=True):
        if not self.result:
            return self.show_empty()
        keep = 0 if top else self.scroll.verticalScrollBar().value()
        self.plan = plan_mod.build(self.result, self.sel)
        p = self.plan
        self._clear()
        self.v.addWidget(self._title(p))
        self.v.addWidget(self._comp_tabs(p))
        reason = self._reason(p)
        if reason:
            self.v.addWidget(reason)
        coach = self._coach_line()
        if coach:
            self.v.addWidget(coach)
        if p.get("pivot"):
            pv = Section("★ 变阵（最该记住的一条）", WARN_C, emphasis=True)
            pv.set_html(p["pivot"].get("html") or "")
            self.v.addWidget(pv)
        if p.get("augments"):
            self.v.addWidget(self._aug_row(p))
        if p.get("board"):
            self.v.addWidget(self._board_block(p))
        self.v.addWidget(self._footer(p))
        self.v.addStretch(1)
        sb = self.scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: sb.setValue(keep))

    # ---------------------------------------------------------- 各块
    def _title(self, p):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        row = QHBoxLayout()
        row.setSpacing(9)
        t = QLabel(p.get("title") or "?")
        t.setStyleSheet("color:%s;font-size:24px;font-weight:bold;" % TX)
        row.addWidget(t)
        if p.get("tier"):
            row.addWidget(chip(p["tier"], TIER_C.get(p["tier"], MUTED), bold=True, size=13))
        meta = QLabel(p.get("meta") or "")
        meta.setStyleSheet("color:%s;font-size:11px;" % MUTED)
        row.addWidget(meta)
        row.addStretch(1)
        btn = QPushButton("复制阵容码")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setStyleSheet("QPushButton{background:#22304a;color:%s;border:1px solid %s;"
                          "border-radius:7px;padding:4px 11px;font-size:11px;}" % (ACC, ACC))
        btn.clicked.connect(lambda: self._copy(p.get("code") or ""))
        row.addWidget(btn)
        v.addLayout(row)
        return w

    def _reason(self, p):
        txt = p.get("reason") or ""
        if not txt:
            return None
        lb = QLabel()
        lb.setTextFormat(Qt.TextFormat.RichText)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:%s;font-size:12px;" % "#a8b3c4")
        lb.setText('<div style="line-height:160%%">%s</div>' % txt)
        return lb

    def _coach_line(self):
        coach = (self.result or {}).get("coach") or {}
        data = coach.get("data") or {}
        if not data or coach.get("fallback"):
            return None
        bits = [data.get("summary"), data.get("roll")]
        bits = [b for b in bits if b]
        if not bits:
            return None
        lb = QLabel('<span style="color:%s">教练（%s）：</span>%s'
                    % (MUTED, coach.get("model") or "LLM", "　".join(bits)))
        lb.setTextFormat(Qt.TextFormat.RichText)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:%s;font-size:12px;" % "#b9c3d2")
        return lb

    def _comp_tabs(self, p):
        """顶部打法切换：强调样式，一屏内换整套思路"""
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab = QLabel("打法")
        lab.setStyleSheet("color:%s;font-size:12px;" % MUTED)
        row.addWidget(lab)
        for o in p.get("others") or []:
            on = (o["index"] == self.sel)
            col = TIER_C.get(o.get("tier") or "", MUTED)
            btn = QPushButton("#%d  %s · %s" % (o["index"] + 1, o["title"], o.get("tier") or "?"))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCheckable(True)
            btn.setChecked(on)
            btn.setStyleSheet(
                "QPushButton{background:%s;color:%s;border:%dpx solid %s;border-radius:8px;"
                "padding:6px 14px;font-size:12px;%s}"
                "QPushButton:hover{background:#243044;}"
                % ("#26364f" if on else "transparent", TX if on else MUTED,
                   2 if on else 1, col if on else LINE,
                   "font-weight:bold;" if on else ""))
            btn.clicked.connect(lambda _=False, k=o["index"]: self._select(k))
            row.addWidget(btn)
        row.addStretch(1)
        return w

    def _titled(self, head, sub=None):
        """标题行（主色竖线 + 标题 + 小字说明），返回 (容器, 竖向布局)"""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(7)
        row = QHBoxLayout()
        row.setSpacing(8)
        bar = QFrame()
        bar.setFixedSize(3, 15)
        bar.setStyleSheet("background:%s;border-radius:2px;" % ACC)
        row.addWidget(bar)
        t = QLabel(head)
        t.setStyleSheet("color:%s;font-size:13px;font-weight:bold;" % ACC)
        row.addWidget(t)
        if sub:
            sb = QLabel(sub)
            sb.setStyleSheet("color:%s;font-size:11px;" % MUTED)
            row.addWidget(sb)
        row.addStretch(1)
        v.addLayout(row)
        return w, v

    def _aug_row(self, p):
        nxt = (self.result or {}).get("next_augment_round")
        w, v = self._titled("强化符文", ("下一轮 %s · 悬停看效果" % nxt) if nxt else "悬停看效果")
        row = QHBoxLayout()
        row.setSpacing(8)
        for a in p["augments"]:
            btn = QToolButton()
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setToolTip(a["tooltip"])
            pm = pixmap(a.get("icon"), 46)
            if pm:
                btn.setIcon(QIcon(pm))
                btn.setIconSize(QSize(44, 44))
            else:
                btn.setText((a["name"] or "?")[:1])
            col = TIER_C.get(str(a.get("tier") or "").upper(), MUTED)
            btn.setStyleSheet(
                "QToolButton{border:1px solid %s;border-radius:8px;background:#141924;"
                "min-width:46px;min-height:46px;color:%s;font-size:16px;}"
                "QToolButton:hover{background:#20293a;}" % (col, col))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(btn)
        row.addStretch(1)
        v.addLayout(row)
        return w

    def _board_block(self, p):
        own = sum(1 for u in (p.get("board") or []) if u.get("owned"))
        w, v = self._titled("站位", "绿框=已有　红框=主C　金边=核心装　%s/%d 已到手"
                           % (own, len(p.get("board") or [])))
        hb = HexBoard()
        hb.set_units(p.get("board") or [])
        v.addWidget(hb)
        return w

    def _footer(self, p):
        ft = p.get("footer") or {}
        f = Fold("识别信息 / 告警", self.collapsed, "footer")
        txt = [ft.get("timings") or ""]
        if ft.get("source"):
            txt.append("字段来源：" + ft["source"])
        for w in ft.get("warnings") or []:
            txt.append("⚠ " + w)
        lb = QLabel("<br>".join(txt))
        lb.setTextFormat(Qt.TextFormat.RichText)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:%s;font-size:11px;" % MUTED)
        f.body.addWidget(lb)
        return f

    # ---------------------------------------------------------- 交互
    def _select(self, k):
        self.sel = k
        self.repaint_all(top=False)

    def _copy(self, text):
        if not text:
            return
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "已复制",
                                "阵容码已复制，进游戏点「阵容码」粘贴即可。")


# ------------------------------------------------------------------ Tab2
class AnnotateTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)
        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        self.view = AnnotationView()
        self.view.clicked.connect(self._on_view_click)
        lv.addWidget(self.view, 1)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.lbl_hint = QLabel("滚轮缩放 · 拖拽平移 · 双击复位 · 点框看取值")
        self.lbl_hint.setStyleSheet("color:%s;font-size:11px;" % MUTED)
        bar.addWidget(self.lbl_hint)
        bar.addStretch(1)
        self.lbl_pick = QLabel("")
        self.lbl_pick.setStyleSheet("color:%s;font-size:12px;font-weight:bold;" % OK_C)
        bar.addWidget(self.lbl_pick)
        lv.addLayout(bar)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)
        self.lbl_sum = QLabel("")
        self.lbl_sum.setWordWrap(True)
        self.lbl_sum.setStyleSheet("color:%s;font-size:12px;" % MUTED)
        rv.addWidget(self.lbl_sum)

        self.filter_row = QHBoxLayout()
        self.filter_row.setSpacing(6)
        self.group_boxes = {}
        rv.addLayout(self.filter_row)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["识别项", "取值", "来源"])
        self.tree.setColumnWidth(0, 185)
        self.tree.setColumnWidth(1, 215)
        self.tree.header().setStretchLastSection(True)
        self.tree.setStyleSheet(
            "QTreeWidget{background:%s;border:1px solid %s;border-radius:8px;"
            "color:%s;font-size:12px;alternate-background-color:#131822;}"
            "QTreeWidget::item{height:22px;}"
            "QTreeWidget::item:selected{background:#22304a;}"
            "QHeaderView::section{background:#1b2130;color:%s;border:0;padding:4px;}"
            % (CARD, LINE, TX, MUTED))
        self.tree.itemClicked.connect(self._on_tree_click)
        rv.addWidget(self.tree, 1)
        split.addWidget(right)
        split.setSizes([900, 480])
        lay.addWidget(split)

    def _build_filters(self, groups):
        while self.filter_row.count():
            it = self.filter_row.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
        self.group_boxes = {}
        for g in groups:
            cb = QCheckBox(g)
            cb.setChecked(True)
            cb.setStyleSheet(
                "QCheckBox{color:%s;font-size:11px;padding:0 2px;}"
                "QCheckBox::indicator{width:11px;height:11px;}"
                % GROUP_C.get(g, ACC))
            cb.stateChanged.connect(self._apply_filters)
            self.filter_row.addWidget(cb)
            self.group_boxes[g] = cb
        cb = QCheckBox("标签")
        cb.setChecked(True)
        cb.setStyleSheet("QCheckBox{color:%s;font-size:11px;}" % MUTED)
        cb.stateChanged.connect(lambda: self.view.set_show_labels(cb.isChecked()))
        self.filter_row.addWidget(cb)
        self.filter_row.addStretch(1)

    def _apply_filters(self):
        on = {g for g, cb in self.group_boxes.items() if cb.isChecked()}
        self.view.set_groups(on)

    def render(self, res):
        self.result = res
        self.view.set_image(res.get("image"))
        items = res.get("annotations") or []
        self.view.set_items(items)
        self.tree.clear()
        st = res.get("state") or {}
        self.lbl_sum.setText("识别到 %d 项标注　·　%s" % (len(items), res.get("timings_text")))
        groups = {}
        for it in items:
            groups.setdefault(it["group"], []).append(it)
        order = ["文本", "商店", "单位", "羁绊", "装备栏", "强化符文", "玩家"]
        seq = order + [g for g in groups if g not in order]
        self._build_filters([g for g in seq if g in groups])
        for g in seq:
            if g not in groups:
                continue
            top = QTreeWidgetItem([g, "%d 项" % len(groups[g]), ""])
            top.setForeground(0, QBrush(QColor(GROUP_C.get(g, ACC))))
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            for it in groups[g]:
                ch = QTreeWidgetItem([it["label"], str(it.get("value") or ""),
                                      str(it.get("source") or "")])
                ch.setData(0, Qt.ItemDataRole.UserRole, it["id"])
                ch.setForeground(1, QBrush(QColor(TX)))
                ch.setForeground(2, QBrush(QColor(MUTED)))
                top.addChild(ch)
            top.setExpanded(True)

    def _on_tree_click(self, item, col):
        iid = item.data(0, Qt.ItemDataRole.UserRole)
        if iid:
            self.view.select(iid)
            self.lbl_pick.setText("%s ｜ %s" % (item.text(0), item.text(1)))

    def _on_view_click(self, iid):
        self.view.select(iid)
        it = next((x for x in (self.result or {}).get("annotations") or [] if x["id"] == iid), None)
        if it:
            self.lbl_pick.setText("%s ｜ %s" % (it["label"], it.get("value")))


# ------------------------------------------------------------------ 主窗口
class MainWindow(QMainWindow):
    def __init__(self, image=None):
        super().__init__()
        self.setWindowTitle("金铲铲 S18 对局助手")
        self.resize(1560, 980)
        self.setAcceptDrops(True)
        self.result = None
        self.worker = None
        self.cache_on = True
        self.busy_since = 0.0
        self._busy = False
        self._show_cache_off_once = False
        self.cur_image = None
        self.pending_image = image if (image and os.path.exists(image)) else None
        self._build()
        self.tick = QTimer(self)
        self.tick.timeout.connect(self._update_busy)
        self.tick.start(120)
        self._start_warmup()

    # ---------------------------------------------------------- UI
    def _build(self):
        central = QWidget()
        central.setStyleSheet("background:%s;" % BG)
        self.setCentralWidget(central)
        v = QVBoxLayout(central)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_open = QPushButton("打开截图…")
        self.btn_open.clicked.connect(self.pick)
        self.btn_reload = QPushButton("重新分析")
        self.btn_reload.clicked.connect(lambda: self.reopen(force=True))
        for b in (self.btn_open, self.btn_reload):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet("QPushButton{background:#22304a;color:%s;border:1px solid %s;"
                            "border-radius:8px;padding:6px 14px;font-size:13px;}"
                            "QPushButton:disabled{background:#1a1f29;color:#5a6478;"
                            "border-color:#2a3140;}" % (TX, ACC))
            bar.addWidget(b)

        bar.addWidget(label("识别", MUTED, 12, wrap=False))
        self.cmb_backend = QComboBox()
        self.cmb_backend.addItems(["ocr（离线，快）", "hybrid（失败回落 VLM）", "vlm（联网，稳）"])
        self.cmb_backend.setStyleSheet(
            "QComboBox{background:#1a1f2a;color:%s;border:1px solid %s;border-radius:7px;"
            "padding:4px 8px;}" % (TX, LINE))
        bar.addWidget(self.cmb_backend)

        self.chk_llm = QCheckBox("LLM 建议")
        self.chk_llm.setChecked(True)
        self.chk_llm.setStyleSheet("QCheckBox{color:%s;font-size:12px;}" % TX)
        bar.addWidget(self.chk_llm)

        self.chk_cache = QCheckBox("缓存")
        self.chk_cache.setChecked(True)
        self.chk_cache.setStyleSheet("QCheckBox{color:%s;font-size:12px;}" % MUTED)
        bar.addWidget(self.chk_cache)

        bar.addStretch(1)
        self.lbl_stat = QLabel("预热中…")
        self.lbl_stat.setStyleSheet("color:%s;font-size:12px;" % MUTED)
        bar.addWidget(self.lbl_stat)
        v.addLayout(bar)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane{border:1px solid %s;border-radius:8px;background:%s;}"
            "QTabBar::tab{background:#141924;color:%s;padding:8px 22px;border:1px solid %s;"
            "border-bottom:0;border-top-left-radius:8px;border-top-right-radius:8px;"
            "margin-right:3px;font-size:13px;}"
            "QTabBar::tab:selected{background:%s;color:%s;font-weight:bold;}"
            % (LINE, PANEL, MUTED, LINE, CARD, TX))
        self.tab_rec = RecommendTab()
        self.tab_ann = AnnotateTab()
        self.tabs.addTab(self.tab_rec, "阵容推荐")
        self.tabs.addTab(self.tab_ann, "识别标注")
        v.addWidget(self.tabs, 1)

    # ---------------------------------------------------------- 预热
    def _start_warmup(self):
        def done(r):
            ms = (r or {}).get("total_ms")
            self.lbl_stat.setText("就绪 · 预热 %sms" % ms)
            if self.pending_image:
                p, self.pending_image = self.pending_image, None
                self.open_image(p)
        w = Worker(pipeline.warm, True)
        w.done.connect(done)
        self.warm_worker = w
        w.start()

    # ---------------------------------------------------------- 打开
    def pick(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择对局截图", os.path.dirname(DEFAULT_IMAGE) or ".",
            "图片 (*.png *.jpg *.jpeg *.bmp)")
        if paths:
            self.open_image(paths[0])

    def open_image(self, path, ignore_cache=False):
        if not os.path.exists(path):
            return
        self.cur_image = path
        backend = ["ocr", "hybrid", "vlm"][self.cmb_backend.currentIndex()]
        use_llm = self.chk_llm.isChecked()
        self.cache_on = self.chk_cache.isChecked()

        key = self._cache_key(path, backend, use_llm)
        if self.cache_on and not ignore_cache:
            hit = self._cache_get(key)
            if hit:
                hit["cached"] = True
                self._show(hit)
                return

        if self.worker and self.worker.isRunning():
            return
        self._set_busy(True, "识别中…")
        self.worker = Worker(pipeline.safe_analyze, path, backend=backend,
                             use_llm=use_llm)
        self.worker.progress.connect(lambda m: self.lbl_stat.setText(m))
        self.worker.done.connect(lambda r: self._on_done(r, key))
        self.busy_since = time.perf_counter()
        self.worker.start()

    def reopen(self, force=False):
        if getattr(self, "cur_image", None):
            self.open_image(self.cur_image, ignore_cache=bool(force))

    def _on_done(self, res, key):
        if not res or not res.get("ok"):
            self._set_busy(False)
            QMessageBox.critical(self, "分析失败",
                                 (res or {}).get("error") or "未知错误")
            return
        self._cache_put(key, res)
        self._show(res)

    def _show(self, res):
        self.result = res
        self.tab_rec.render(res)
        self.tab_ann.render(res)
        if res.get("cached"):
            self._set_busy(False, "缓存命中（原分析 %s）" % (res.get("timings_text") or "-"))
        else:
            self._set_busy(False, res.get("timings_text") or "")
        self.tabs.setTabText(0, "阵容推荐 · %s" % ((res.get("top") or {}).get("title") or ""))
        # 布局完成后焦点会把滚动条带下去，这里补一次归零
        for delay in (0, 60, 200):
            QTimer.singleShot(delay, lambda: self.tab_rec.scroll.verticalScrollBar().setValue(0))

    def _set_busy(self, busy, msg=""):
        self.btn_open.setEnabled(not busy)
        self.btn_reload.setEnabled(not busy)
        self._busy = busy
        if msg:
            self.lbl_stat.setText(msg)
        if busy:
            self.busy_since = time.perf_counter()

    def _update_busy(self):
        if getattr(self, "_busy", False):
            self.lbl_stat.setText("分析中… %.1fs" % (time.perf_counter() - self.busy_since))

    # ---------------------------------------------------------- 缓存
    def _cache_key(self, path, backend, use_llm):
        h = hashlib.sha1()
        try:
            with open(path, "rb") as f:
                h.update(f.read(1 << 20))
        except Exception:
            h.update(path.encode("utf-8", "ignore"))
        h.update(("|%s|%s|v2" % (backend, use_llm)).encode())
        return h.hexdigest()[:20]

    def _cache_get(self, key):
        p = os.path.join(OUT_CACHE, key + ".json")
        if not os.path.exists(p):
            return None
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _cache_put(self, key, res):
        try:
            os.makedirs(OUT_CACHE, exist_ok=True)
            p = os.path.join(OUT_CACHE, key + ".json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False)
        except Exception:
            pass

    # ---------------------------------------------------------- 拖拽
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        for u in ev.mimeData().urls():
            p = u.toLocalFile()
            if p and os.path.splitext(p)[1].lower() in (".png", ".jpg", ".jpeg", ".bmp"):
                self.open_image(p)
                break


QSS = """
QWidget{font-family:"Microsoft YaHei UI","Microsoft YaHei",sans-serif;font-size:13px;color:%s;}
QToolTip{background:#1b2130;color:%s;border:1px solid %s;padding:4px;}
QScrollBar:vertical{background:%s;width:10px;margin:0;}
QScrollBar::handle:vertical{background:#333c4e;border-radius:5px;min-height:30px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
""" % (TX, TX, LINE, PANEL)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    app.setApplicationName("金铲铲S18对局助手")

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    shot = None
    if "--shot" in sys.argv:
        i = sys.argv.index("--shot")
        shot = sys.argv[i + 1] if len(sys.argv) > i + 1 else "shot.png"
        args = [a for a in args if a != shot]

    w = MainWindow(args[0] if args else None)
    w.show()

    if shot:
        def grab():
            base = os.path.splitext(shot)[0]
            for idx, suffix in ((0, "_tab1"), (1, "_tab2")):
                w.tabs.setCurrentIndex(idx)
                QApplication.processEvents()
                if idx == 0:
                    w.tab_rec.scroll.verticalScrollBar().setValue(0)
                w.repaint()
                QApplication.processEvents()
                time.sleep(0.2)
                QApplication.processEvents()
                w.grab().save(base + suffix + ".png")
            # 再补一张滚到底的（看装备/站位）
            w.tabs.setCurrentIndex(0)
            QApplication.processEvents()
            sb = w.tab_rec.scroll.verticalScrollBar()
            sb.setValue(sb.maximum())
            w.repaint()
            QApplication.processEvents()
            time.sleep(0.2)
            w.grab().save(base + "_tab1b.png")
            print("saved", base + "_tab1.png", base + "_tab2.png", base + "_tab1b.png")
            app.quit()
        QTimer.singleShot(16000, grab)
        app.exec()
        return

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
