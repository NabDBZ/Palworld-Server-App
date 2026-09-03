import sys, os, gc, time
from import_libs import *
from loading_manager import show_information, run_with_loading
from palworld_aio.ui.chrome.styles import ThemeManager
from PySide6.QtWidgets import QApplication, QFileDialog
from palsav.commands.convert import main as convert_main
def convert_sav_to_json(input_file, output_file):
    old_argv = sys.argv
    try:
        sys.argv = ['convert', input_file, '--output', output_file, '--force']
        convert_main()
    finally:
        sys.argv = old_argv
def convert_json_to_sav(input_file, output_file):
    old_argv = sys.argv
    try:
        sys.argv = ['convert', input_file, '--output', output_file, '--force']
        convert_main()
    finally:
        sys.argv = old_argv
def file_picker(ext):
    app = QApplication.instance() or QApplication(sys.argv)
    if not QApplication.instance():
        ThemeManager.apply_global()
    path = None
    if ext == 'sav':
        path, _ = QFileDialog.getOpenFileName(None, 'Select JSON File', '', 'JSON Files (*.json)')
    elif ext == 'json':
        path, _ = QFileDialog.getOpenFileName(None, 'Select SAV File', '', 'SAV Files (*.sav)')
    return path
def convert_generic(ext):
    input_file = file_picker(ext)
    if not input_file:
        return False
    root, _ = os.path.splitext(input_file)
    output_path = root + ('.sav' if ext == 'sav' else '.json')
    parent = QApplication.activeWindow()
    def task():
        if ext == 'sav':
            convert_json_to_sav(input_file, output_path)
        else:
            convert_sav_to_json(input_file, output_path)
        gc.collect()
        time.sleep(0.5)
    def on_done(_):
        print(f'Converted {input_file} to {output_path}')
        show_information(parent, t('tool.convert.done'), t('tool.convert.level_done', source=input_file, target=output_path))
    run_with_loading(on_done, task, parent=parent)
    return True
def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ['sav', 'json']:
        print('Usage: script.py <sav|json>')
        exit(1)
    if not convert_generic(sys.argv[1]):
        exit(1)
if __name__ == '__main__':
    main()