"""NeonCut - interface (PySide6).

Janela de controle (previa + opcoes) e uma janela de saida limpa, so com o video,
para capturar no Streamlabs com "Captura de janela".
"""

import os
import shutil
import sys
import threading

import numpy as np
from PySide6.QtCore import QObject, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QKeySequence, QPainter, QPainterPath, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QPushButton, QScrollArea, QSizePolicy,
    QSlider, QStackedWidget, QVBoxLayout, QWidget,
)

import engine as eng

ACCENT = "#8b5cf6"
OUTPUT_TITLE = "NeonCut - Saída"
COLOR_PRESETS = ["#1b1030", "#0b132b", "#102a1e", "#2b0f12", "#111111", "#f2f2f2", "#00b140", "#0047bb"]

QSS = f"""
* {{ font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 13px; color: #e7e7ee; }}
QMainWindow, #root {{ background: #0e0e13; }}
#sidebar {{ background: #15151c; border-left: 1px solid #23232d; }}
#card {{ background: #15151c; border: 1px solid #23232d; border-radius: 14px; }}
#title {{ font-size: 18px; font-weight: 600; }}
#section {{ color: #8d8d9c; font-size: 11px; font-weight: 600; letter-spacing: 1px; margin-top: 10px; }}
#muted {{ color: #8d8d9c; }}
#value {{ color: #b9a4ff; font-weight: 600; }}
#chip {{ background: #1d1d26; border: 1px solid #2a2a35; border-radius: 10px; padding: 4px 10px; color: #b5b5c3; }}
#error {{ background: #2a1316; border: 1px solid #5a2229; border-radius: 10px; padding: 8px 12px; color: #ffb4bd; }}

QPushButton {{ background: #1f1f29; border: 1px solid #2c2c38; border-radius: 9px; padding: 8px 14px; }}
QPushButton:hover {{ background: #272733; border-color: #3a3a48; }}
QPushButton:pressed {{ background: #1a1a22; }}
QPushButton#primary {{ background: {ACCENT}; border: none; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: #9b72ff; }}
QPushButton#nav {{ background: transparent; border: none; border-radius: 8px; padding: 8px 4px; color: #9a9aa8; font-weight: 600; }}
QPushButton#nav:hover {{ color: #e7e7ee; background: #1d1d26; }}
QPushButton#nav:checked {{ color: white; background: #262033; }}
QPushButton#seg {{ background: #1a1a22; border: 1px solid #2a2a35; border-radius: 0; padding: 7px 6px; color: #a5a5b3; }}
QPushButton#seg:checked {{ background: #2c2342; border-color: {ACCENT}; color: white; }}
QPushButton#segFirst {{ background: #1a1a22; border: 1px solid #2a2a35; border-top-left-radius: 9px; border-bottom-left-radius: 9px;
    border-top-right-radius: 0; border-bottom-right-radius: 0; padding: 7px 6px; color: #a5a5b3; }}
QPushButton#segFirst:checked {{ background: #2c2342; border-color: {ACCENT}; color: white; }}
QPushButton#segLast {{ background: #1a1a22; border: 1px solid #2a2a35; border-top-right-radius: 9px; border-bottom-right-radius: 9px;
    border-top-left-radius: 0; border-bottom-left-radius: 0; padding: 7px 6px; color: #a5a5b3; }}
QPushButton#segLast:checked {{ background: #2c2342; border-color: {ACCENT}; color: white; }}
QPushButton#swatch {{ border-radius: 14px; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; padding: 0; }}

QSlider::groove:horizontal {{ height: 4px; background: #2a2a35; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: #d9ccff; }}

QComboBox {{ background: #1a1a22; border: 1px solid #2a2a35; border-radius: 9px; padding: 7px 10px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: #1a1a22; border: 1px solid #2a2a35; selection-background-color: #2c2342; outline: 0; }}

QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{ width: 34px; height: 18px; border-radius: 9px; background: #2a2a35; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; }}

QListWidget {{ background: transparent; border: none; outline: 0; }}
QListWidget::item {{ border: 2px solid transparent; border-radius: 10px; padding: 2px; color: #a5a5b3; }}
QListWidget::item:hover {{ border-color: #3a3a48; }}
QListWidget::item:selected {{ border-color: {ACCENT}; background: #1d1828; color: white; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; }}
QScrollBar::handle:vertical {{ background: #2c2c38; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def bgr_to_qimage(frame):
    h, w = frame.shape[:2]
    return QImage(frame.data, w, h, 3 * w, QImage.Format_BGR888).copy()


class VideoView(QWidget):
    """Desenha o quadro mantendo a proporcao, com cantos arredondados opcionais."""

    def __init__(self, radius=12, placeholder="Iniciando câmera..."):
        super().__init__()
        self.image = None
        self.radius = radius
        self.placeholder = placeholder
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 180)

    def set_image(self, image):
        self.image = image
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.image is None:
            p.setPen(QColor("#6d6d7c"))
            p.drawText(self.rect(), Qt.AlignCenter, self.placeholder)
            return
        iw, ih = self.image.width(), self.image.height()
        k = min(self.width() / iw, self.height() / ih)
        w, h = iw * k, ih * k
        target = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        if self.radius:
            path = QPainterPath()
            path.addRoundedRect(target, self.radius, self.radius)
            p.setClipPath(path)
        p.drawImage(target, self.image)


class OutputWindow(QWidget):
    """Janela so com o video, para o Streamlabs capturar."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(OUTPUT_TITLE)
        self.setStyleSheet("background: black;")
        self.view = VideoView(radius=0, placeholder="")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        self.resize(960, 540)


class SliderRow(QWidget):
    def __init__(self, title, lo, hi, value, on_change, suffix="", default=None):
        super().__init__()
        self.suffix = suffix
        self.default = value if default is None else default
        self.on_change = on_change
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(QLabel(title))
        top.addStretch()
        self.value = QLabel()
        self.value.setObjectName("value")
        top.addWidget(self.value)
        lay.addLayout(top)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setValue(value)
        self.slider.valueChanged.connect(self._changed)
        self.slider.setToolTip("Clique duplo no valor para restaurar")
        lay.addWidget(self.slider)
        self._show(value)
        self.value.mouseDoubleClickEvent = lambda _: self.slider.setValue(self.default)

    def _show(self, v):
        self.value.setText(f"{v:+d}{self.suffix}" if self.slider.minimum() < 0 else f"{v}{self.suffix}")

    def _changed(self, v):
        self._show(v)
        self.on_change(v)

    def set(self, v):
        self.slider.setValue(v)


class Segmented(QWidget):
    def __init__(self, options, current, on_change):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for i, (key, label) in enumerate(options):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setObjectName("segFirst" if i == 0 else "segLast" if i == len(options) - 1 else "seg")
            b.clicked.connect(lambda _=False, k=key: on_change(k))
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
        self.set(current)

    def set(self, key):
        if key in self.buttons:
            self.buttons[key].setChecked(True)


def section(text):
    lbl = QLabel(text.upper())
    lbl.setObjectName("section")
    return lbl


def muted(text):
    lbl = QLabel(text)
    lbl.setObjectName("muted")
    lbl.setWordWrap(True)
    return lbl


class Page(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget(objectName="pageInner")
        inner.setStyleSheet("#pageInner { background: transparent; }")
        self.lay = QVBoxLayout(inner)
        self.lay.setContentsMargins(18, 8, 18, 18)
        self.lay.setSpacing(8)
        self.setWidget(inner)

    def add(self, w):
        self.lay.addWidget(w)
        return w

    def finish(self):
        self.lay.addStretch()


class Bridge(QObject):
    status = Signal(str, bool)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NeonCut")
        self.resize(1360, 800)
        self.s = eng.Settings.load()
        self.latest = None
        self.latest_lock = threading.Lock()
        self.output = OutputWindow()

        self.bridge = Bridge()
        self.bridge.status.connect(self._show_status)
        self.engine = eng.Engine(self.s, self._on_frame, lambda m, e: self.bridge.status.emit(m, e))

        self.save_timer = QTimer(self, singleShot=True, interval=400, timeout=self.s.save)
        self._build()
        self._shortcuts()

        self.timer = QTimer(self, interval=15, timeout=self._tick)
        self.timer.start()
        self.engine.start()

    # ---------- layout ----------
    def _build(self):
        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        left = QVBoxLayout()
        left.setContentsMargins(22, 18, 22, 18)
        left.setSpacing(14)
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(str(eng.APP_DIR / "assets" / "icon.png")).scaled(
            30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(logo)
        title = QLabel("NeonCut", objectName="title")
        head.addWidget(title)
        head.addSpacing(10)
        self.fps_chip = QLabel("-- fps", objectName="chip")
        self.cam_chip = QLabel("Câmera", objectName="chip")
        self.vcam_chip = QLabel("Câmera virtual: desligada", objectName="chip")
        self.ai_chip = QLabel("IA", objectName="chip")
        for c in (self.fps_chip, self.ai_chip, self.cam_chip, self.vcam_chip):
            head.addWidget(c)
        head.addStretch()
        out_btn = QPushButton("Abrir janela de saída", objectName="primary")
        out_btn.setCursor(Qt.PointingHandCursor)
        out_btn.setToolTip("Janela limpa para capturar no Streamlabs (F)")
        out_btn.clicked.connect(self.open_output)
        head.addWidget(out_btn)
        left.addLayout(head)

        self.error = QLabel(objectName="error")
        self.error.setWordWrap(True)
        self.error.hide()
        left.addWidget(self.error)

        card = QFrame(objectName="card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 10, 10, 10)
        self.preview = VideoView()
        cl.addWidget(self.preview)
        left.addWidget(card, 1)
        left.addWidget(muted("Atalhos:  N / P troca o fundo  ·  B desfoque  ·  M espelhar  ·  F janela de saída"))
        lay.addLayout(left, 1)

        side = QWidget(objectName="sidebar")
        side.setFixedWidth(380)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 14, 0, 0)
        sl.setSpacing(6)
        nav = QHBoxLayout()
        nav.setContentsMargins(12, 0, 12, 0)
        nav.setSpacing(2)
        self.pages = QStackedWidget()
        group = QButtonGroup(self)
        self.nav_buttons = []
        for i, (name, page) in enumerate([
            ("Fundo", self._page_background()),
            ("Recorte", self._page_matte()),
            ("Pessoa", self._page_person()),
            ("Câmera", self._page_camera()),
            ("Saída", self._page_output()),
        ]):
            b = QPushButton(name, objectName="nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self.pages.setCurrentIndex(i))
            group.addButton(b)
            nav.addWidget(b)
            self.nav_buttons.append(b)
            self.pages.addWidget(page)
            if i == 0:
                b.setChecked(True)
        sl.addLayout(nav)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #23232d;")
        sl.addWidget(line)
        sl.addWidget(self.pages, 1)
        lay.addWidget(side)

    def _page_background(self):
        p = Page()
        p.add(section("Tipo de fundo"))
        self.bg_mode = p.add(Segmented(
            [("image", "Imagem"), ("blur", "Desfoque"), ("color", "Cor"), ("none", "Original")],
            self.s.bg_mode, self.set_bg_mode))

        self.bg_stack = QStackedWidget()
        p.add(self.bg_stack)

        # Imagem / video
        img = QWidget()
        il = QVBoxLayout(img)
        il.setContentsMargins(0, 0, 0, 0)
        il.addWidget(section("Galeria"))
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListWidget.IconMode)
        self.gallery.setIconSize(QSize(150, 84))
        self.gallery.setGridSize(QSize(164, 112))
        self.gallery.setResizeMode(QListWidget.Adjust)
        self.gallery.setMovement(QListWidget.Static)
        self.gallery.setMinimumHeight(250)
        self.gallery.setSpacing(2)
        self.gallery.itemClicked.connect(lambda it: self.set_bg_file(it.data(Qt.UserRole)))
        il.addWidget(self.gallery)
        row = QHBoxLayout()
        add = QPushButton("+ Adicionar fundo")
        add.clicked.connect(self.add_backgrounds)
        folder = QPushButton("Abrir pasta")
        folder.clicked.connect(lambda: os.startfile(eng.BG_DIR))
        row.addWidget(add, 1)
        row.addWidget(folder)
        il.addLayout(row)
        il.addWidget(muted("Imagens (.jpg, .png) ou vídeos em loop (.mp4, .webm). Pode arrastar arquivos para cá."))
        il.addWidget(section("Ajustes do fundo"))
        il.addWidget(SliderRow("Desfoque (profundidade)", 0, 30, self.s.bg_blur, lambda v: self.set("bg_blur", v), default=0))
        il.addWidget(SliderRow("Escurecer", 0, 80, self.s.bg_dim, lambda v: self.set("bg_dim", v), "%", default=0))
        self.bg_stack.addWidget(img)

        # Desfoque
        blur = QWidget()
        bl = QVBoxLayout(blur)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(section("Desfoque"))
        bl.addWidget(SliderRow("Intensidade", 2, 50, self.s.blur_strength, lambda v: self.set("blur_strength", v), default=18))
        bl.addWidget(muted("Desfoca o seu ambiente real, como o modo retrato do celular."))
        bl.addStretch()
        self.bg_stack.addWidget(blur)

        # Cor
        color = QWidget()
        col = QVBoxLayout(color)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(section("Cor sólida"))
        sw = QGridLayout()
        for i, c in enumerate(COLOR_PRESETS):
            b = QPushButton(objectName="swatch")
            b.setStyleSheet(f"background: {c}; border: 2px solid #2a2a35;")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=c: self.set_color(c))
            sw.addWidget(b, 0, i)
        col.addLayout(sw)
        pick = QPushButton("Escolher outra cor...")
        pick.clicked.connect(self.pick_color)
        col.addWidget(pick)
        col.addWidget(SliderRow("Escurecer", 0, 80, self.s.bg_dim, lambda v: self.set("bg_dim", v), "%", default=0))
        col.addStretch()
        self.bg_stack.addWidget(color)

        # Original
        none = QWidget()
        nl = QVBoxLayout(none)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.addWidget(muted("Mostra a câmera sem trocar o fundo. Os ajustes da aba Pessoa continuam valendo."))
        nl.addStretch()
        self.bg_stack.addWidget(none)

        self._sync_bg_stack()
        self.refresh_gallery()
        p.finish()
        p.setAcceptDrops(True)
        p.dragEnterEvent = lambda e: e.acceptProposedAction() if e.mimeData().hasUrls() else None
        p.dropEvent = lambda e: self._import([u.toLocalFile() for u in e.mimeData().urls()])
        return p

    def _page_matte(self):
        p = Page()
        p.add(section("Modelo de IA"))
        p.add(Segmented([(2, "GPU (máxima)"), (0, "CPU preciso"), (1, "CPU rápido")], self.s.model, self._set_model))
        self.model_help = p.add(muted(""))

        # Opcoes do modelo na GPU (Robust Video Matting)
        self.gpu_opts = QWidget()
        gl = QVBoxLayout(self.gpu_opts)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.addWidget(section("Detalhe da IA"))
        gl.addWidget(Segmented([(180, "180p"), (240, "240p"), (360, "360p")], self.s.rvm_detail,
                               lambda v: self.set("rvm_detail", v)))
        gl.addWidget(muted("Resolução em que a IA enxerga você; a borda é refinada em resolução cheia. "
                           "180p é o mais leve (30 fps); 240p e 360p pegam mais detalhe, mas pesam mais na placa."))
        despill = QCheckBox("Remover reflexo de cor do fundo")
        despill.setChecked(self.s.despill)
        despill.toggled.connect(lambda v: self.set("despill", v))
        gl.addWidget(despill)
        gl.addWidget(muted("Usa a cor real estimada pela IA nas bordas e no cabelo, sem o tom da parede atrás de você."))
        p.add(self.gpu_opts)

        p.add(section("Borda"))
        p.add(SliderRow("Ajuste do recorte", -30, 30, self.s.edge_shift, lambda v: self.set("edge_shift", v), default=0))
        p.add(muted("Negativo pega mais área em volta de você; positivo recorta mais justo e corta sobras do fundo."))
        p.add(SliderRow("Limpar sobras", 0, 100, self.s.cleanup, lambda v: self.set("cleanup", v), "%", default=60))
        p.add(muted("Mantém só você e apaga objetos atrás (cadeira, roupas, pôster). Se cortar seu ombro "
                    "ou roupa escura, diminua. 0% desliga."))

        # Opcoes so do MediaPipe (o RVM ja entrega borda suave e estavel)
        self.cpu_opts = QWidget()
        cl = QVBoxLayout(self.cpu_opts)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(SliderRow("Suavidade da borda", 0, 12, self.s.feather, lambda v: self.set("feather", v), default=4))
        cl.addWidget(SliderRow("Estabilidade", 0, 85, self.s.stability, lambda v: self.set("stability", v), "%", default=40))
        cl.addWidget(muted("Mais estabilidade tira o tremido da borda, mas deixa um leve rastro em movimentos rápidos."))
        p.add(self.cpu_opts)
        self._sync_model_opts()
        p.add(section("Diagnóstico"))
        mask = QCheckBox("Ver máscara (branco = você)")
        mask.setChecked(self.s.show_mask)
        mask.toggled.connect(lambda v: self.set("show_mask", v))
        p.add(mask)
        p.finish()
        return p

    def _page_person(self):
        p = Page()
        p.add(section("Imagem"))
        rows = [
            p.add(SliderRow("Brilho", -50, 50, self.s.brightness, lambda v: self.set("brightness", v), default=0)),
            p.add(SliderRow("Contraste", -50, 50, self.s.contrast, lambda v: self.set("contrast", v), default=0)),
            p.add(SliderRow("Saturação", -100, 100, self.s.saturation, lambda v: self.set("saturation", v), default=0)),
        ]
        p.add(section("Enquadramento"))
        rows += [
            p.add(SliderRow("Tamanho", 50, 150, self.s.scale, lambda v: self.set("scale", v), "%", default=100)),
            p.add(SliderRow("Posição horizontal", -50, 50, self.s.offset_x, lambda v: self.set("offset_x", v), default=0)),
            p.add(SliderRow("Posição vertical", -50, 50, self.s.offset_y, lambda v: self.set("offset_y", v), default=0)),
        ]
        p.add(muted("Mova e redimensione você sobre o fundo, por exemplo para ficar no canto da tela."))
        reset = QPushButton("Restaurar padrões")
        reset.clicked.connect(lambda: [r.set(r.default) for r in rows])
        p.add(reset)
        p.finish()
        return p

    def _page_camera(self):
        p = Page()
        p.add(section("Dispositivo"))
        row = QHBoxLayout()
        self.cam_combo = QComboBox()
        self.cam_combo.activated.connect(lambda _: self.set("camera", self.cam_combo.currentData()))
        row.addWidget(self.cam_combo, 1)
        refresh = QPushButton("Atualizar")
        refresh.clicked.connect(self.refresh_cameras)
        row.addWidget(refresh)
        w = QWidget()
        w.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        p.add(w)
        p.add(muted("A webcam só pode ser usada por um programa por vez: desative a fonte de webcam no Streamlabs."))
        self.refresh_cameras()

        p.add(section("Resolução"))
        res = p.add(QComboBox())
        for w_, h_ in eng.RESOLUTIONS:
            res.addItem(f"{w_} x {h_}")
        current = (self.s.width, self.s.height)
        res.setCurrentIndex(eng.RESOLUTIONS.index(current) if current in eng.RESOLUTIONS else 1)
        res.activated.connect(lambda i: self._set_resolution(eng.RESOLUTIONS[i]))

        p.add(section("Quadros por segundo"))
        fps = p.add(QComboBox())
        for f in (15, 24, 30, 60):
            fps.addItem(f"{f} fps", f)
        fps.setCurrentIndex(max(0, fps.findData(self.s.fps)))
        fps.activated.connect(lambda _: self.set("fps", fps.currentData()))

        p.add(section("Exposição"))
        p.add(Segmented([("fixed", "Fluida (fps fixo)"), ("auto", "Automática")], self.s.exposure_mode,
                        self._set_exposure_mode))
        self.exposure_rows = QWidget()
        er = QVBoxLayout(self.exposure_rows)
        er.setContentsMargins(0, 0, 0, 0)
        er.addWidget(SliderRow("Exposição", -8, -3, self.s.exposure, lambda v: self.set("exposure", v), default=-5))
        er.addWidget(SliderRow("Ganho (sensibilidade)", 0, 255, self.s.gain, lambda v: self.set("gain", v), default=64))
        p.add(self.exposure_rows)
        self.exposure_rows.setVisible(self.s.exposure_mode == "fixed")
        p.add(muted("Com pouca luz, o modo automático deixa a camera lenta (7 a 15 fps). O modo fluido segura "
                    "30 fps; se ficar escuro, suba o ganho ou o brilho na aba Pessoa, ou melhore a iluminação."))

        p.add(section("Orientação"))
        mirror = p.add(QCheckBox("Espelhar imagem"))
        mirror.setChecked(self.s.mirror)
        mirror.toggled.connect(lambda v: self.set("mirror", v))
        self.mirror_box = mirror
        p.finish()
        return p

    def _page_output(self):
        p = Page()
        p.add(section("Streamlabs"))
        steps = QLabel(
            "<ol style='margin-left:-20px; line-height:150%'>"
            "<li>Clique em <b>Abrir janela de saída</b>.</li>"
            "<li>No Streamlabs: <b>+ Fonte → Captura de janela</b>.</li>"
            f"<li>Escolha a janela <b>{OUTPUT_TITLE}</b> (aparece como [pythonw.exe]).</li>"
            "<li>Pode minimizar este painel; deixe a janela de saída aberta.</li></ol>")
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.RichText)
        p.add(steps)
        btn = p.add(QPushButton("Abrir janela de saída", objectName="primary"))
        btn.clicked.connect(self.open_output)

        p.add(section("Câmera virtual"))
        vc = p.add(QCheckBox("Enviar para câmera virtual"))
        vc.setChecked(self.s.virtualcam)
        vc.toggled.connect(lambda v: self.set("virtualcam", v))
        p.add(muted("Precisa de um driver de câmera virtual compatível (ex.: OBS Virtual Camera). "
                    "Sem driver, use a Captura de janela, que funciona igual."))
        p.finish()
        return p

    # ---------- acoes ----------
    def set(self, key, value):
        setattr(self.s, key, value)
        self.save_timer.start()

    def set_bg_mode(self, mode):
        self.set("bg_mode", mode)
        self.bg_mode.set(mode)
        self._sync_bg_stack()

    def _sync_bg_stack(self):
        self.bg_stack.setCurrentIndex(["image", "blur", "color", "none"].index(self.s.bg_mode))

    def set_bg_file(self, name):
        self.set("bg_file", name)
        self.set_bg_mode("image")

    def set_color(self, c):
        self.set("bg_color", c)
        self.set_bg_mode("color")

    def pick_color(self):
        c = QColorDialog.getColor(QColor(self.s.bg_color), self, "Cor do fundo")
        if c.isValid():
            self.set_color(c.name())

    def _set_model(self, model):
        self.set("model", model)
        self._sync_model_opts()

    def _sync_model_opts(self):
        gpu = self.s.model == 2
        self.gpu_opts.setVisible(gpu)
        self.cpu_opts.setVisible(not gpu)
        self.model_help.setText(
            "Matting na placa de vídeo (Robust Video Matting + DirectML): recorta fio a fio do cabelo "
            "e a borda já vem estável." if gpu else
            "Segmentação MediaPipe no processador. Preciso: melhor em cabelo e mãos. Rápido: para PCs mais fracos.")

    def _set_exposure_mode(self, mode):
        self.set("exposure_mode", mode)
        self.exposure_rows.setVisible(mode == "fixed")

    def _set_resolution(self, wh):
        self.s.width, self.s.height = wh
        self.save_timer.start()

    def refresh_gallery(self):
        self.gallery.clear()
        files = eng.list_backgrounds()
        for path in files:
            thumb = eng.thumbnail(path, 150, 84)
            icon = QIcon(QPixmap.fromImage(bgr_to_qimage(np.ascontiguousarray(thumb)))) if thumb is not None else QIcon()
            label = path.stem if len(path.stem) <= 20 else path.stem[:18] + "…"
            if path.suffix.lower() in eng.VIDEO_EXT:
                label = "▶ " + label
            it = QListWidgetItem(icon, label)
            it.setData(Qt.UserRole, path.name)
            it.setToolTip(path.name)
            self.gallery.addItem(it)
            if path.name == self.s.bg_file:
                it.setSelected(True)
        if files and not self.s.bg_file:
            self.s.bg_file = files[0].name
            self.gallery.item(0).setSelected(True)

    def add_backgrounds(self):
        exts = " ".join(f"*{e}" for e in sorted(eng.IMAGE_EXT | eng.VIDEO_EXT))
        paths, _ = QFileDialog.getOpenFileNames(self, "Adicionar fundos", "", f"Imagens e vídeos ({exts})")
        self._import(paths)

    def _import(self, paths):
        last = None
        for src in paths:
            src = os.path.abspath(src)
            ext = os.path.splitext(src)[1].lower()
            if ext not in eng.IMAGE_EXT | eng.VIDEO_EXT or not os.path.isfile(src):
                continue
            dst = eng.BG_DIR / os.path.basename(src)
            if os.path.abspath(dst) != src:
                shutil.copy2(src, dst)
            last = dst.name
        if last:
            self.s.bg_file = last
            self.refresh_gallery()
            self.set_bg_file(last)

    def refresh_cameras(self):
        self.cam_combo.clear()
        names = eng.list_cameras()
        for n in names:
            self.cam_combo.addItem(n + ("  (virtual)" if eng.is_virtual(n) else ""), n)
        _, current = eng.resolve_camera(self.s.camera)
        self.cam_combo.setCurrentIndex(max(0, self.cam_combo.findData(current)))

    def step_background(self, delta):
        n = self.gallery.count()
        if not n:
            return
        names = [self.gallery.item(i).data(Qt.UserRole) for i in range(n)]
        i = names.index(self.s.bg_file) if self.s.bg_file in names else -delta
        i = (i + delta) % n
        self.gallery.setCurrentRow(i)
        self.set_bg_file(names[i])

    def open_output(self):
        self.output.show()
        self.output.raise_()
        self.output.activateWindow()

    def _shortcuts(self):
        for key, fn in [
            ("N", lambda: self.step_background(1)),
            ("P", lambda: self.step_background(-1)),
            ("B", lambda: self.set_bg_mode("image" if self.s.bg_mode == "blur" else "blur")),
            ("M", lambda: self.mirror_box.toggle()),
            ("F", self.open_output),
        ]:
            QShortcut(QKeySequence(key), self, activated=fn)

    # ---------- quadros ----------
    def _on_frame(self, frame):  # thread do motor
        with self.latest_lock:
            self.latest = frame

    def _tick(self):
        with self.latest_lock:
            frame, self.latest = self.latest, None
        if frame is not None:
            img = bgr_to_qimage(frame)
            self.preview.set_image(img)
            if self.output.isVisible():
                self.output.view.set_image(img)
        self.fps_chip.setText(f"{self.engine.fps:.0f} fps")
        self.ai_chip.setText(f"IA: {self.engine.matter_device or '...'}")
        dev = self.engine.virtualcam_device
        self.vcam_chip.setText(f"Câmera virtual: {dev}" if dev else
                               "Câmera virtual: " + ("sem driver" if self.s.virtualcam else "desligada"))

    def _show_status(self, msg, is_error):
        if is_error:
            self.error.setText(msg)
            self.error.show()
        else:
            self.error.hide()
            self.cam_chip.setText(msg.replace("Camera: ", ""))

    def closeEvent(self, e):
        self.s.save()
        self.engine.stop()
        self.output.close()
        super().closeEvent(e)


def main():
    try:  # icone proprio na barra de tarefas (senao o Windows agrupa como python.exe)
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NeonCut.App")
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("NeonCut")
    app.setWindowIcon(QIcon(str(eng.APP_DIR / "assets" / "icon.png")))
    app.setStyleSheet(QSS)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
