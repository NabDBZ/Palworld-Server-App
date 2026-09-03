from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QStackedWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QCursor
from palworld_aio import constants
from i18n import t
from palworld_aio.ui.tabs.docs.wiki_tab import WikiTab

_SUB_TAB_STYLE = (
    'QPushButton { background: transparent; color: #94a3b8; border: none; '
    'border-bottom: 2px solid transparent; padding: 6px 16px; font-size: 12px; font-weight: 600; }'
    'QPushButton:hover { color: #e2e8f0; }'
    'QPushButton[active=true] { color: #7DD3FC; border-bottom: 2px solid #7DD3FC; }'
)

class DocsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sub_tab_bar = QHBoxLayout()
        sub_tab_bar.setContentsMargins(10, 4, 10, 0)
        sub_tab_bar.setSpacing(0)

        self._sub_btns = {}
        for sid, skey in [('wiki', 'docs.wiki')]:
            btn = QPushButton(t(skey) if t else skey)
            btn.setFixedHeight(32)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setProperty('active', False)
            btn.setStyleSheet(_SUB_TAB_STYLE)
            btn.clicked.connect(lambda checked, s=sid: self._switch_sub_tab(s))
            self._sub_btns[sid] = btn
            sub_tab_bar.addWidget(btn)

        sub_tab_bar.addStretch()
        layout.addLayout(sub_tab_bar)

        self._sub_stack = QStackedWidget()
        self.wiki_tab = WikiTab(self)
        self._sub_stack.addWidget(self.wiki_tab)
        layout.addWidget(self._sub_stack, 1)

        self._switch_sub_tab('wiki')

    def _switch_sub_tab(self, tab_id):
        idx = {'wiki': 0}.get(tab_id, 0)
        self._sub_stack.setCurrentIndex(idx)
        for sid, btn in self._sub_btns.items():
            active = sid == tab_id
            btn.setProperty('active', active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def refresh(self):
        self.wiki_tab.refresh()

    def refresh_labels(self):
        for sid, skey in [('wiki', 'docs.wiki')]:
            if sid in self._sub_btns:
                self._sub_btns[sid].setText(t(skey) if t else skey)
        self.wiki_tab.refresh_labels()
