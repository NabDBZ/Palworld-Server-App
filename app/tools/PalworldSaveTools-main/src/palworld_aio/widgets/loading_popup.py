from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QProgressBar, QHBoxLayout, QPushButton, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, QEvent
from PySide6.QtGui import QPixmap, QCursor, QFont
import random, time, os
from i18n import t
from resource_resolver import get_base_dir, resource_path, get_data_base
class LoadingPopup(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._setup_ui()
        self.fade_animation = None
        self._is_visible = False
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self._show_fallback()
        layout.addWidget(self.label)
    def _show_fallback(self):
        self.label.setText('Loading...')
        self.label.setStyleSheet("\n            QLabel {\n                color: #7DD3FC;\n                font-size: 24px;\n                font-weight: bold;\n                font-family: 'Segoe UI',Arial;\n                background: rgba(18,20,24,0.95);\n                border-radius: 12px;\n                padding: 40px;\n            }\n        ")
        self.setFixedSize(200, 120)
    def show_with_fade(self):
        if self._is_visible:
            return
        self._center_on_screen()
        self.setWindowOpacity(0.0)
        self.show()
        self.fade_animation = QPropertyAnimation(self, b'windowOpacity')
        self.fade_animation.setDuration(300)
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.setEasingCurve(QEasingCurve.InOutQuad)
        self.fade_animation.start()
        self._is_visible = True
    def hide_with_fade(self, on_complete=None):
        if not self._is_visible:
            if on_complete:
                on_complete()
            return
        self.fade_animation = QPropertyAnimation(self, b'windowOpacity')
        self.fade_animation.setDuration(300)
        self.fade_animation.setStartValue(1.0)
        self.fade_animation.setEndValue(0.0)
        self.fade_animation.setEasingCurve(QEasingCurve.InOutQuad)
        def on_fade_complete():
            self.hide()
            self._is_visible = False
            if on_complete:
                on_complete()
        self.fade_animation.finished.connect(on_fade_complete)
        self.fade_animation.start()
    def _center_on_screen(self):
        parent = self.parent()
        size = self.size()
        if parent and hasattr(parent, 'geometry'):
            parent_rect = parent.geometry()
            x = parent_rect.x() + (parent_rect.width() - size.width()) // 2
            y = parent_rect.y() + (parent_rect.height() - size.height()) // 2
            self.move(x, y)
        else:
            from PySide6.QtWidgets import QApplication
            screen = QApplication.primaryScreen().availableGeometry()
            x = (screen.width() - size.width()) // 2
            y = (screen.height() - size.height()) // 2
            self.move(x, y)
    def closeEvent(self, event):
        super().closeEvent(event)

class LoadingOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setFixedSize(850, 500)
        self._parent = parent
        self._phrases = ['LOADING...']
        self._start_ts = None
        self._phrase_timer = QTimer(self)
        self._phrase_timer.timeout.connect(self._cycle_phrase)
        self._phrase_timer.setInterval(3000)
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._update_elapsed)
        self._tick_timer.setInterval(250)
        self._setup_ui()
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        c = QFrame()
        c.setObjectName('loaderFrame')
        c.setStyleSheet('QFrame#loaderFrame { background: rgba(18,20,24,0.96); border-radius: 16px; border: 1px solid rgba(125,211,252,0.12); }')
        cl = QVBoxLayout(c)
        cl.setContentsMargins(30, 20, 30, 20)
        cl.setSpacing(8)
        icon_lbl = QLabel()
        icon_lbl.setAlignment(Qt.AlignCenter)
        p = resource_path(get_base_dir(), 'Xenolord.webp')
        if not os.path.exists(p):
            p = resource_path(get_base_dir(), 'logo.png')
        if os.path.exists(p):
            pix = QPixmap(p)
            icon_lbl.setPixmap(pix.scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        icon_lbl.setStyleSheet('border: none; background: transparent;')
        cl.addWidget(icon_lbl)
        cl.addSpacing(4)
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setFixedHeight(4)
        bar.setStyleSheet('QProgressBar { background: rgba(255,255,255,0.06); border: none; border-radius: 2px; } QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #38bdf8,stop:1 #7c3aed); border-radius: 2px; }')
        bl = QHBoxLayout()
        bl.addStretch()
        bl.addWidget(bar)
        bl.addStretch()
        cl.addLayout(bl)
        self.label = QLabel('LOADING...')
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setStyleSheet('color: #e2e8f0; font-size: 15px; font-weight: 600; border: none; background: transparent;')
        self._opacity = QGraphicsOpacityEffect(self.label)
        self.label.setGraphicsEffect(self._opacity)
        cl.addWidget(self.label)
        self._time_lbl = QLabel('00:00')
        self._time_lbl.setAlignment(Qt.AlignCenter)
        self._time_lbl.setStyleSheet('color: rgba(148,163,184,0.4); font-size: 11px; border: none; background: transparent;')
        cl.addWidget(self._time_lbl)
        layout.addWidget(c)
        self._center_on_parent()
    def show_overlay(self, phrases=None):
        if phrases:
            self._phrases = phrases
        self._start_ts = time.time()
        self.label.setText(random.choice(self._phrases))
        self._center_on_parent()
        self.show()
        self.activateWindow()
        self.raise_()
        self._phrase_timer.start()
        self._tick_timer.start()
    def hide_overlay(self):
        self._phrase_timer.stop()
        self._tick_timer.stop()
        self.hide()
    def _center_on_parent(self):
        if self._parent:
            g = self._parent.geometry()
            x = g.x() + (g.width() - self.width()) // 2
            y = g.y() + (g.height() - self.height()) // 2
            self.move(x, y)
    def _cycle_phrase(self):
        anim = QPropertyAnimation(self._opacity, b'opacity')
        anim.setDuration(300)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self._change_phrase)
        anim.start()
    def _change_phrase(self):
        self.label.setText(random.choice(self._phrases))
        anim = QPropertyAnimation(self._opacity, b'opacity')
        anim.setDuration(300)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start()
    def _update_elapsed(self):
        if self._start_ts:
            e = time.time() - self._start_ts
            self._time_lbl.setText(f'{int(e // 60):02d}:{int(e % 60):02d}')