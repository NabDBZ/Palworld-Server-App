import os
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QWidget, QFrame, QGridLayout
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from i18n import t, get_language
from palworld_aio import constants
from resource_resolver import resource_path

HEADER_COLOR = '#4a90e2'
TEXT_COLOR = '#e0e0e0'
MUTED_COLOR = '#94a3b8'
SUBSECTION_COLOR = '#7DD3FC'
BG_COLOR = '#0A0B0E'
CARD_BG = '#121418'
BORDER_COLOR = '#1E2128'

SECTION_HTML = '''<div style="color: {text_color}; font-family: '{font_family}'; font-size: 12px;">
<h3 style="color: {header_color}; margin: 0 0 4px 0;">{title}</h3>
{body}
</div>'''

PAGE_HTML = '''<div style="color: {text_color}; font-family: '{font_family}'; font-size: 12px;">
{body}
</div>'''

SECTION_KEYS = [
    ('intro', 'tab_guide.intro_page'),
    ('map', 'tab_guide.section.map'),
    ('tools', 'tab_guide.section.tools'),
    ('base_inventory', 'tab_guide.section.base_inventory'),
    ('player_inventory', 'tab_guide.section.player_inventory'),
    ('pal_editor', 'tab_guide.section.pal_editor'),
    ('players', 'tab_guide.section.players'),
    ('guilds', 'tab_guide.section.guilds'),
    ('bases', 'tab_guide.section.bases'),
    ('exclusions', 'tab_guide.section.exclusions'),
    ('docs', 'tab_guide.section.docs'),
]

FMT = dict(
    text_color=TEXT_COLOR, header_color=HEADER_COLOR,
    font_family=constants.FONT_FAMILY
)


class _TocBtn(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setFont(QFont(constants.FONT_FAMILY, 11))
        self.setStyleSheet(f'''
            QPushButton {{
                color: {SUBSECTION_COLOR}; background: transparent;
                border: 1px solid transparent; border-radius: 4px;
                padding: 3px 8px; text-align: left;
            }}
            QPushButton:hover {{
                color: {HEADER_COLOR}; background: rgba(74,144,226,0.08);
                border-color: rgba(74,144,226,0.2);
            }}
            QPushButton:pressed {{
                color: #FFFFFF; background: rgba(74,144,226,0.15);
            }}
        ''')


class TabGuideDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t('tab_guide.title') if t else 'Tab Usage Guide')
        self.setModal(True)
        self.setMinimumSize(720, 580)
        self.resize(780, 660)
        self._page_label = None
        self._current_anchor = 'intro'
        self._toc_btns = {}
        self._setup_ui()

    def _build_page_html(self, anchor, body):
        if anchor == 'intro':
            html = PAGE_HTML.format(body=body, **FMT)
        else:
            prefix = dict(SECTION_KEYS).get(anchor)
            title = t(f'{prefix}.title') if t and t(f'{prefix}.title') else anchor.title()
            html = SECTION_HTML.format(title=title, body=body, **FMT)
        return html

    def _load_section_body(self, anchor):
        lang = get_language()
        lang_dir = lang.split('_')[0]
        base = constants.get_base_path()
        path = resource_path(base, 'tab_guide', lang_dir, f'{anchor}.html')
        if not os.path.exists(path):
            path = resource_path(base, 'tab_guide', 'en', f'{anchor}.html')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except (OSError, IOError):
            return ''

    def _switch_page(self, anchor):
        self._current_anchor = anchor
        body = self._load_section_body(anchor)
        if self._page_label:
            self._page_label.setText(self._build_page_html(anchor, body))
            self._scroll_area.verticalScrollBar().setValue(0)
        for key, btn in self._toc_btns.items():
            btn.setStyleSheet(self._toc_btn_style(key == anchor))

    def _toc_btn_style(self, active=False):
        if active:
            return f'''
                QPushButton {{
                    color: #FFFFFF; background: rgba(74,144,226,0.18);
                    border: 1px solid rgba(74,144,226,0.35); border-radius: 4px;
                    padding: 3px 8px; text-align: left; font-weight: bold;
                }}
            QPushButton:hover {{ background: rgba(74,144,226,0.25); }}
            QPushButton:pressed {{ color: #FFFFFF; background: rgba(74,144,226,0.35); }}
        '''
        return f'''
            QPushButton {{
                color: {SUBSECTION_COLOR}; background: transparent;
                border: 1px solid transparent; border-radius: 4px;
                padding: 3px 8px; text-align: left;
            }}
            QPushButton:hover {{
                color: {HEADER_COLOR}; background: rgba(74,144,226,0.08);
                border-color: rgba(74,144,226,0.2);
            }}
            QPushButton:pressed {{
                color: #FFFFFF; background: rgba(74,144,226,0.15);
            }}
        '''

    def refresh_labels(self):
        self.setWindowTitle(t('tab_guide.title') if t else 'Tab Usage Guide')
        if hasattr(self, '_title_label'):
            self._title_label.setText(t('tab_guide.title') if t else 'Tab Usage Guide')
        if hasattr(self, '_subtitle_label'):
            self._subtitle_label.setText(t('tab_guide.subtitle') if t else 'Click behaviors, shortcuts, and tips for every section')
        if hasattr(self, '_footer_label'):
            self._footer_label.setText(t('tab_guide.footer') if t else 'Tip: Right-click menus are your friend — always check them for deeper options in every tab.')
        if hasattr(self, '_toc_title_label'):
            self._toc_title_label.setText(t('tab_guide.toc_title') if t else 'Table of Contents — click a page to open:')
        if hasattr(self, '_close_btn'):
            self._close_btn.setText(t('button.close') if t else 'Close')
        for anchor, prefix in SECTION_KEYS:
            label_text = t(f'{prefix}.toc')
            btn = self._toc_btns.get(anchor)
            if btn and label_text:
                btn.setText(label_text)
        if self._page_label:
            body = self._load_section_body(self._current_anchor)
            self._page_label.setText(self._build_page_html(self._current_anchor, body))

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Header ---
        header_frame = QFrame()
        header_frame.setStyleSheet(f'background-color: {BG_COLOR}; border-bottom: 1px solid {BORDER_COLOR};')
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(20, 12, 20, 12)
        self._title_label = QLabel(t('tab_guide.title') if t else 'Tab Usage Guide')
        self._title_label.setFont(QFont(constants.FONT_FAMILY, 16, QFont.Bold))
        self._title_label.setStyleSheet(f'color: {HEADER_COLOR};')
        header_layout.addWidget(self._title_label)
        header_layout.addStretch()
        self._subtitle_label = QLabel(t('tab_guide.subtitle') if t else 'Click behaviors, shortcuts, and tips for every section')
        self._subtitle_label.setFont(QFont(constants.FONT_FAMILY, 10))
        self._subtitle_label.setStyleSheet(f'color: {MUTED_COLOR};')
        header_layout.addWidget(self._subtitle_label)
        layout.addWidget(header_frame)

        # --- Scroll area: TOC + Stacked pages ---
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setStyleSheet(f'''
            QScrollArea {{ background-color: {BG_COLOR}; border: none; }}
        ''')

        scroll_content = QWidget()
        scroll_content.setStyleSheet(f'background-color: {BG_COLOR};')
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(24, 12, 24, 16)
        scroll_layout.setSpacing(0)

        # -- TOC --
        toc_frame = QFrame()
        toc_frame.setStyleSheet(f'background-color: {CARD_BG}; border: 1px solid {BORDER_COLOR}; border-radius: 8px; margin: 4px 0 12px 0;')
        toc_layout = QVBoxLayout(toc_frame)
        toc_layout.setContentsMargins(14, 10, 14, 10)
        toc_layout.setSpacing(6)
        self._toc_title_label = QLabel(t('tab_guide.toc_title') if t else 'Table of Contents — click a page to open:')
        self._toc_title_label.setFont(QFont(constants.FONT_FAMILY, 11, QFont.Bold))
        self._toc_title_label.setStyleSheet(f'color: {HEADER_COLOR}; background: transparent;')
        toc_layout.addWidget(self._toc_title_label)
        grid = QGridLayout()
        grid.setSpacing(4)
        cols = 3
        for i, (anchor, prefix) in enumerate(SECTION_KEYS):
            label_text = t(f'{prefix}.toc')
            btn = _TocBtn(label_text if label_text else anchor.title())
            btn.clicked.connect(lambda checked, a=anchor: self._switch_page(a))
            self._toc_btns[anchor] = btn
            grid.addWidget(btn, i // cols, i % cols)
        toc_layout.addLayout(grid)
        scroll_layout.addWidget(toc_frame)

        scroll_layout.addSpacing(4)

        # -- Single page label (content swapped on navigation) --
        self._page_label = QLabel()
        self._page_label.setWordWrap(True)
        self._page_label.setTextFormat(Qt.RichText)
        self._page_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._page_label.setStyleSheet(f'background-color: {BG_COLOR}; color: {TEXT_COLOR}; padding: 0;')
        scroll_layout.addWidget(self._page_label)
        scroll_layout.addStretch()

        self._scroll_area.setWidget(scroll_content)
        layout.addWidget(self._scroll_area, 1)

        # Start on intro page
        self._switch_page('intro')

        # --- Footer ---
        footer_frame = QFrame()
        footer_frame.setStyleSheet(f'background-color: {CARD_BG}; border-top: 1px solid {BORDER_COLOR};')
        footer_layout = QHBoxLayout(footer_frame)
        footer_layout.setContentsMargins(20, 10, 20, 10)
        self._footer_label = QLabel(t('tab_guide.footer') if t else 'Tip: Right-click menus are your friend — always check them for deeper options in every tab.')
        self._footer_label.setFont(QFont(constants.FONT_FAMILY, 10))
        self._footer_label.setStyleSheet(f'color: {MUTED_COLOR};')
        footer_layout.addWidget(self._footer_label)
        footer_layout.addStretch()
        self._close_btn = QPushButton(t('button.close') if t else 'Close')
        self._close_btn.setFixedSize(100, 32)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setStyleSheet(f'''
            QPushButton {{
                background-color: {HEADER_COLOR}; color: white; border: none;
                border-radius: 6px; font-weight: bold; font-size: 12px;
            }}
            QPushButton:hover {{ background-color: #5BA3E6; }}
            QPushButton:pressed {{ background-color: #3A7BC8; }}
        ''')
        self._close_btn.clicked.connect(self.accept)
        footer_layout.addWidget(self._close_btn)
        layout.addWidget(footer_frame)

        self.setStyleSheet(f'QDialog {{ background-color: {BG_COLOR}; }}')
