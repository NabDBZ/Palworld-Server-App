from PySide6.QtWidgets import QWidget, QGridLayout, QLabel, QFrame, QPushButton, QApplication, QStylePainter, QStyleOptionButton, QStyle
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPainter, QFontMetrics
from i18n import t
from loading_manager import show_information, show_warning
from palworld_aio import constants
from palworld_aio.ui.chrome.sidebar_widget import NerdBtn
class StatsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.stats_before = {}
        self.is_dark_mode = True
        self._setup_ui()
    def _setup_ui(self):
        layout = QGridLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)
        self.stat_labels = {}
        self.stat_key_labels = {}
        sections = [('before', 'deletion.stats.before'), ('after', 'deletion.stats.after'), ('result', 'deletion.stats.result')]
        fields = [('guilds', 'deletion.stats.guilds'), ('bases', 'deletion.stats.bases'), ('players', 'deletion.stats.players'), ('pals', 'deletion.stats.pals')]
        try:
            import nerdfont as nf
            copy_icon = nf.icons.get('nf-cod-copy', '📋')
        except:
            copy_icon = '📋'
        copy_btn = NerdBtn(copy_icon)
        copy_btn.setFixedSize(30, 24)
        copy_btn.setStyleSheet(f'\n            QPushButton {{\n                background-color: transparent;\n                border: none;\n                font-size: 14px;\n            }}\n            QPushButton:hover {{\n                background-color: {constants.BUTTON_HOVER};\n                border-radius: 4px;\n            }}\n        ')
        copy_btn.clicked.connect(self._copy_stats_to_clipboard)
        layout.addWidget(copy_btn, 0, len(sections) + 1, Qt.AlignRight)
        empty_label = QLabel('')
        layout.addWidget(empty_label, 0, 0)
        for col, (sec_key, sec_label_key) in enumerate(sections, start=1):
            header_label = QLabel(t(sec_label_key) if t else sec_key.title())
            header_label.setFont(QFont(constants.FONT_FAMILY, constants.FONT_SIZE, QFont.Bold))
            header_label.setStyleSheet(f'color: {constants.EMPHASIS};')
            header_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(header_label, 0, col)
            self.stat_key_labels[f'header_{sec_key}'] = (header_label, sec_label_key)
        for row, (field_key, field_label_key) in enumerate(fields, start=1):
            field_label = QLabel(t(field_label_key) + ':' if t else field_key.title() + ':')
            field_label.setFont(QFont(constants.FONT_FAMILY, constants.FONT_SIZE))
            field_label.setStyleSheet(f'color: {constants.MUTED};')
            field_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            layout.addWidget(field_label, row, 0)
            self.stat_key_labels[f'field_{field_key}'] = (field_label, field_label_key)
            for col, (sec_key, _) in enumerate(sections, start=1):
                value_label = QLabel('0')
                value_label.setFont(QFont(constants.FONT_FAMILY, constants.FONT_SIZE, QFont.Bold))
                value_label.setStyleSheet(f'color: {constants.EMPHASIS};')
                value_label.setAlignment(Qt.AlignCenter)
                layout.addWidget(value_label, row, col)
                key = f'{sec_key}_{field_key}'
                self.stat_labels[key] = value_label
    def update_stats(self, stats_dict, section='after'):
        section = section.lower()
        key_map = {'players': 'players', 'guilds': 'guilds', 'bases': 'bases', 'pals': 'pals'}
        for key, value in stats_dict.items():
            internal_key = key_map.get(key.lower())
            if internal_key:
                label_key = f'{section}_{internal_key}'
                if label_key in self.stat_labels:
                    self.stat_labels[label_key].setText(str(value))
    def refresh_stats_before(self, stats_dict):
        self.stats_before = dict(stats_dict)
        self.update_stats(stats_dict, 'before')
        zero_stats = {k: 0 for k in stats_dict}
        self.update_stats(zero_stats, 'after')
        self.update_stats(zero_stats, 'result')
    def refresh_stats_after(self, stats_dict):
        self.update_stats(stats_dict, 'after')
        if self.stats_before:
            result = {}
            key_map = {'players': 'Players', 'guilds': 'Guilds', 'bases': 'Bases', 'pals': 'Pals'}
            for internal_key, external_key in key_map.items():
                before_val = self.stats_before.get(external_key, 0)
                after_val = stats_dict.get(external_key, 0)
                if isinstance(before_val, str):
                    before_val = int(before_val) if before_val.isdigit() else 0
                if isinstance(after_val, str):
                    after_val = int(after_val) if after_val.isdigit() else 0
                result[external_key] = before_val - after_val
            self.update_stats(result, 'result')
    def refresh_labels(self):
        for key, (label, label_key) in self.stat_key_labels.items():
            if key.startswith('header_'):
                label.setText(t(label_key) if t else label_key.split('.')[-1].title())
            elif key.startswith('field_'):
                label.setText((t(label_key) if t else label_key.split('.')[-1].title()) + ':')
    def _get_stat_value(self, key):
        if key in self.stat_labels:
            return self.stat_labels[key].text().strip()
        return '0'
    def _copy_stats_to_clipboard(self):
        copy_content = 'PalworldSaveTools\n\n'
        fields = ['guilds', 'bases', 'players', 'pals']
        sections = ['before', 'after', 'result']
        header_template = '{type:<15}{before:<12}{after:<12}{result}'
        data_template = '{type:<15}{before:<12}{after:<12}{result}'
        before_header = t('deletion.stats.before') if t else 'Before'
        after_header = t('deletion.stats.after') if t else 'After'
        result_header = t('deletion.stats.result') if t else 'Result'
        field_header = t('deletion.stats.field') if t else 'Field'
        copy_content += header_template.format(type=field_header, before=before_header, after=after_header, result=result_header) + '\n'
        for field in fields:
            field_name = t(f'deletion.stats.{field}') if t else field.title()
            before_val = self._get_stat_value(f'before_{field}')
            after_val = self._get_stat_value(f'after_{field}')
            result_val = self._get_stat_value(f'result_{field}')
            copy_content += data_template.format(type=field_name, before=before_val, after=after_val, result=result_val) + '\n'
        try:
            clipboard = QApplication.clipboard()
            clipboard.setText(copy_content)
            show_information(self, t('status.copy_success_title') if t else 'Copied', t('status.copy_success_body') if t else 'Stats copied to clipboard!')
        except Exception:
            show_warning(self, t('status.copy_fail_title') if t else 'Error', t('status.copy_fail_body') if t else 'Failed to copy to clipboard.')