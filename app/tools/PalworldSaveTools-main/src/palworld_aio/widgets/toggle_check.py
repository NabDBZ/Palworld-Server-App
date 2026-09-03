from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont, QMouseEvent
from palworld_aio import constants
from palworld_aio.ui.chrome.sidebar_widget import NerdBtn
try:
    import nerdfont as nf
except:
    class nf:
        icons = {'nf-fa-check': '\uf00c'}


class ToggleCheckBtn(QWidget):
    toggled = Signal(bool)

    def __init__(self, label, parent=None):
        super().__init__(parent)
        self._checked = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._icon_btn = NerdBtn('')
        self._icon_btn.setFixedSize(20, 20)
        self._icon_btn.setFont(QFont(constants.FONT_FAMILY_NERD, 12))
        self._icon_btn.clicked.connect(lambda: self._toggle(True))
        layout.addWidget(self._icon_btn)
        self._label = QLabel(label)
        self._label.setStyleSheet('color: #e2e8f0; background: transparent;')
        layout.addWidget(self._label)
        self._update_style()

    def _toggle(self, from_btn=False):
        self._checked = not self._checked
        self._update_style()
        self.toggled.emit(self._checked)

    def mousePressEvent(self, event: QMouseEvent):
        child = self.childAt(event.pos())
        if child is self._label:
            self._toggle()
        super().mousePressEvent(event)

    def _update_style(self):
        if self._checked:
            self._icon_btn.setText(nf.icons.get('nf-fa-check', '\uf00c'))
            self._icon_btn.setStyleSheet(
                'NerdBtn { background: rgba(125,211,252,0.2); color: #7DD3FC;'
                ' border: 1px solid rgba(125,211,252,0.3); border-radius: 4px; }'
            )
        else:
            self._icon_btn.setText('')
            self._icon_btn.setStyleSheet(
                'NerdBtn { background: rgba(255,255,255,0.05);'
                ' border: 1px solid rgba(255,255,255,0.1); border-radius: 4px; }'
            )

    def setChecked(self, checked):
        self._checked = checked
        self._update_style()

    def isChecked(self):
        return self._checked

    def setText(self, text):
        self._label.setText(text)
