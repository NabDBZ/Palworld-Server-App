from PySide6.QtWidgets import QSplitter, QSplitterHandle, QPushButton, QVBoxLayout, QWidget
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QCursor
class CollapsibleSplitterHandle(QSplitterHandle):
    toggle_clicked = Signal()
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._collapsed = False
        self._setup_ui()
    def _setup_ui(self):
        if self.orientation() == Qt.Horizontal:
            self.setFixedWidth(16)
        else:
            self.setFixedHeight(16)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch()
        self.toggle_btn = QPushButton()
        self.toggle_btn.setObjectName('collapseToggle')
        self.toggle_btn.setFixedSize(QSize(14, 50))
        self.toggle_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.toggle_btn.clicked.connect(self.toggle_clicked.emit)
        self._update_button_icon()
        layout.addWidget(self.toggle_btn, 0, Qt.AlignCenter)
        layout.addStretch()
    def set_collapsed(self, collapsed):
        self._collapsed = collapsed
        self._update_button_icon()
    def _update_button_icon(self):
        if self._collapsed:
            self.toggle_btn.setText('◀')
        else:
            self.toggle_btn.setText('▶')
    def mouseMoveEvent(self, event):
        pass
    def mousePressEvent(self, event):
        pass
    def mouseReleaseEvent(self, event):
        pass
class CollapsibleSplitter(QSplitter):
    collapsed_changed = Signal(bool)
    def __init__(self, orientation=Qt.Horizontal, collapsible_index=1, parent=None):
        super().__init__(orientation, parent)
        self.setObjectName('collapsibleSplitter')
        self.setChildrenCollapsible(False)
        self._collapsible_index = collapsible_index
        self._is_collapsed = False
        self._expanded_width = 380
        self._stored_sizes = None
        self._handle_connected = False
    def createHandle(self):
        handle = CollapsibleSplitterHandle(self.orientation(), self)
        handle.toggle_clicked.connect(self.toggle_collapse)
        return handle
    def setExpandedWidth(self, width):
        self._expanded_width = width
    def addWidget(self, widget):
        super().addWidget(widget)
        self._update_all_handles()
    def _update_all_handles(self):
        for i in range(1, self.count()):
            handle = self.handle(i)
            if isinstance(handle, CollapsibleSplitterHandle):
                handle.set_collapsed(self._is_collapsed)
    def toggle_collapse(self):
        if self._is_collapsed:
            self.expand()
        else:
            self.collapse()
    def collapse(self):
        if self._is_collapsed:
            return
        self._stored_sizes = self.sizes()
        new_sizes = list(self.sizes())
        total = sum(new_sizes)
        new_sizes[self._collapsible_index] = 0
        new_sizes[1 - self._collapsible_index] = total
        self.setSizes(new_sizes)
        self._is_collapsed = True
        self._update_all_handles()
        self.collapsed_changed.emit(True)
    def expand(self):
        if not self._is_collapsed:
            return
        if self._stored_sizes:
            self.setSizes(self._stored_sizes)
        else:
            total = sum(self.sizes())
            new_sizes = [0, 0]
            new_sizes[self._collapsible_index] = self._expanded_width
            new_sizes[1 - self._collapsible_index] = total - self._expanded_width
            self.setSizes(new_sizes)
        self._is_collapsed = False
        self._update_all_handles()
        self.collapsed_changed.emit(False)
    def is_collapsed(self):
        return self._is_collapsed