from __future__ import annotations
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
MAX_ITERATIONS = 50
class ChangeLog:
    def __init__(self):
        self.changes = []
    def record(self, file_path, description):
        rel = os.path.relpath(file_path)
        self.changes.append({'file': rel, 'description': description})
    def print_report(self):
        print()
        print('=' * 60)
        print('  AUTO-UPDATE CHANGE REPORT')
        print('=' * 60)
        if not self.changes:
            print('  No changes were needed.')
            return
        for i, c in enumerate(self.changes, 1):
            print(f"\n  {i}. {c['file']}")
            print(f"     {c['description']}")
        print(f'\n  Total: {len(self.changes)} file(s) modified')
def get_pst_root():
    return Path(__file__).resolve().parent.parent.parent.parent.parent
def get_src_dir():
    return get_pst_root() / 'src'
def get_subprocess_env():
    return {**os.environ, 'PYTHONPATH': str(get_src_dir()), 'PYTHONIOENCODING': 'utf-8', 'PYTHONWARNINGS': 'ignore'}
def run_convert(sav_path):
    src_dir = get_src_dir()
    output = tempfile.mktemp(suffix='.json')
    proc = subprocess.run([sys.executable, '-m', 'palsav.commands.convert', str(sav_path), '--to-json', '-o', output, '--force'], capture_output=True, text=True, cwd=get_pst_root(), env=get_subprocess_env(), timeout=120)
    return (proc, output)
def run_roundtrip(sav_path):
    src_dir = get_src_dir()
    temp_sav = tempfile.mktemp(suffix='.sav')
    temp_json = tempfile.mktemp(suffix='.json')
    env = get_subprocess_env()
    proc_json = subprocess.run([sys.executable, '-m', 'palsav.commands.convert', str(sav_path), '--to-json', '-o', temp_json, '--force'], capture_output=True, text=True, cwd=get_pst_root(), env=env, timeout=120)
    if proc_json.returncode != 0:
        return ('json_fail', proc_json.stderr)
    proc_sav = subprocess.run([sys.executable, '-m', 'palsav.commands.convert', temp_json, '--from-json', '-o', temp_sav, '--force'], capture_output=True, text=True, cwd=get_pst_root(), env=env, timeout=120)
    if proc_sav.returncode != 0:
        return ('sav_fail', proc_sav.stderr)
    with open(sav_path, 'rb') as f:
        original = f.read()
    with open(temp_sav, 'rb') as f:
        resaved = f.read()
    return ('ok', None) if original == resaved else ('mismatch', None)
def parse_error(stderr, stdout):
    output = stderr + '\n' + stdout
    match = re.search('Exception: (.+)', output)
    if not match:
        return None
    error_msg = match.group(1).strip()
    frames = re.findall('File "([^"]+)", line (\\d+)', output)
    result = {'error_message': error_msg, 'stack_frames': frames, 'file_line': frames[-1] if frames else None}
    if 'EOF not reached for module type' in error_msg:
        module_type = error_msg.split('module type')[-1].strip()
        result['type'] = 'unknown_module_type'
        result['module_type'] = module_type
    elif 'EOF not reached' in error_msg:
        result['type'] = 'eof_not_reached'
    elif 'Unknown map object concrete model' in error_msg:
        result['type'] = 'unknown_concrete_model'
        id_match = re.search("'([^']+)'", error_msg)
        if id_match:
            result['object_id'] = id_match.group(1)
    elif 'Unknown property value type' in error_msg:
        result['type'] = 'unknown_property_value_type'
        type_match = re.search('Unknown property value type: (\\w+)', error_msg)
        if type_match:
            result['missing_type'] = type_match.group(1)
    elif 'Unknown property type' in error_msg:
        result['type'] = 'unknown_property_type'
    elif 'not in database' in error_msg:
        result['type'] = 'missing_game_data'
    else:
        result['type'] = 'unknown'
    return result
FIX_PATTERNS = {'map_concrete_model_module_decode_eof': {'old': "    if not reader.eof():\n        raise Exception(f'Warning: EOF not reached for module type {module_type}')", 'new': "    if not reader.eof():\n        data['unknown_bytes'] = [int(b) for b in reader.read_to_end()]"}, 'map_concrete_model_module_encode_default': {'pattern': "case 'EPalMapObjectConcreteModelModuleType::RequireElementalAction':", 'insert_before': '    encoded_bytes = writer.bytes()', 'insert': "        case _:\n            writer.write(bytes(p.get('unknown_bytes', [])))\n"}, 'general_eof_raise': {'old': "    if not reader.eof():\n        raise Exception('Warning: EOF not reached')", 'new': "    if not reader.eof():\n        data['unknown_bytes'] = [int(b) for b in reader.read_to_end()]"}, 'base_camp_eof': {'old': "    if not reader.eof():\n        raise Exception('Warning: EOF not reached')", 'new': "    if not reader.eof():\n        data['unknown_bytes'] = [int(b) for b in reader.read_to_end()]"}, 'character_eof': {'old': "    if not reader.eof():\n        raise Exception('Warning: EOF not reached')", 'new': "    if not reader.eof():\n        data['unknown_bytes'] = [int(b) for b in reader.read_to_end()]"}, 'work_eof': {'old': "    if not reader.eof():\n        raise Exception(f'Warning: EOF not reached for {work_type}, remaining bytes: {reader.read_to_end()!r}')", 'new': "    if not reader.eof():\n        data['unknown_bytes'] = [int(b) for b in reader.read_to_end()]"}, 'map_concrete_model_eof': {'pattern': 'if not reader.eof():\n        raise Exception(f"Warning: EOF not reached for', 'replace_lines': True}, 'encode_append_unknown_bytes': {'pattern': '    encoded_bytes = writer.bytes()', 'insert_before': '    encoded_bytes = writer.bytes()', 'insert': "    if 'unknown_bytes' in p:\n        writer.write(bytes(p['unknown_bytes']))\n"}, 'encode_append_trailing_bytes': {'pattern': '    encoded_bytes = writer.bytes()', 'insert_before': '    encoded_bytes = writer.bytes()', 'insert': "    if 'trailing_bytes' in p:\n        writer.write(bytes(p['trailing_bytes']))\n"}}
def apply_string_fix(file_path, old_string, new_string, changelog, dry_run):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    if old_string not in content:
        return False
    if not dry_run:
        backup_file(file_path)
    content = content.replace(old_string, new_string)
    if not dry_run:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    return True
def apply_insert_fix(file_path, insert_before, insert_text, changelog, dry_run):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    if insert_text.strip() in content:
        return False
    if insert_before not in content:
        return False
    if not dry_run:
        backup_file(file_path)
    content = content.replace(insert_before, insert_text + insert_before)
    if not dry_run:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    return True
LINE_RAISE_EOF = "        raise Exception('Warning: EOF not reached')"
LINE_RAISE_EOF_2 = "            raise Exception('Warning: EOF not reached')"
def detect_variable_name(content, raise_line_idx):
    lines = content.split('\n')
    if raise_line_idx + 1 < len(lines):
        rm = re.match('^\\s+return\\s+(\\w+)', lines[raise_line_idx + 1])
        if rm:
            return rm.group(1)
    start = max(0, raise_line_idx - 40)
    for i in range(raise_line_idx - 1, start - 1, -1):
        stripped = lines[i].strip()
        m = re.match('^(\\w+)\\s*=\\s*\\{', stripped)
        if m:
            candidate = m.group(1)
            if candidate not in ('guild',):
                return candidate
        m = re.match('^(\\w+):\\s*dict', stripped)
        if m:
            return m.group(1)
        m = re.match('^(\\w+)\\s*\\|\\|?=\\s*\\{', stripped)
        if m:
            return m.group(1)
    return None
def get_eof_raise_line(content):
    lines = content.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()
        eof_before = lines[i - 1] if i > 0 else ''
        if 'if not reader.eof()' in eof_before and 'raise Exception' in stripped:
            return (i, eof_before, line)
    return (None, None, None)
def handle_eof_replacement(file_path, changelog, dry_run):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    lines = content.split('\n')
    eof_line_idx, if_line, raise_line = get_eof_raise_line(content)
    if eof_line_idx is None:
        return False
    var_name = detect_variable_name(content, eof_line_idx)
    if not var_name:
        return False
    if_line_text = lines[eof_line_idx - 1]
    indent = re.match('^(\\s*)', if_line_text).group(1)
    old = if_line_text + '\n' + lines[eof_line_idx]
    new_lines_str = f"{indent}if not reader.eof():\n{indent}    {var_name}['unknown_bytes'] = [int(b) for b in reader.read_to_end()]"
    if not dry_run:
        backup_file(file_path)
    content = content.replace(old, new_lines_str)
    if not dry_run:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    changelog.record(file_path, f'Replaced EOF raise with trailing-bytes capture (var={var_name})')
    return True
def handle_encode_fix(file_path, is_match_based, changelog, dry_run):
    if is_match_based:
        for key in ['map_concrete_model_module_encode_default']:
            pat = FIX_PATTERNS[key]
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if pat['insert'].strip() in content:
                continue
            if pat['pattern'] in content and pat['insert_before'] in content:
                if not dry_run:
                    backup_file(file_path)
                content = content.replace(pat['insert_before'], pat['insert'] + pat['insert_before'])
                if not dry_run:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                changelog.record(file_path, f'Added default case to encode match ({key})')
                return True
    else:
        for name in ['encode_append_unknown_bytes', 'encode_append_trailing_bytes']:
            pat = FIX_PATTERNS[name]
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if pat['insert'].strip() in content:
                continue
            if pat['insert_before'] in content:
                if not dry_run:
                    backup_file(file_path)
                content = content.replace(pat['insert_before'], pat['insert'] + pat['insert_before'])
                if not dry_run:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                changelog.record(file_path, f'Added unknown-bytes preservation to encode ({name})')
                return True
    return False
PROP_VALUE_READER_CALLS = {'Int64Property': 'self.i64()', 'UInt64Property': 'self.u64()', 'UInt16Property': 'self.u16()', 'FixedPoint64Property': 'self.i32()', 'FloatProperty': 'self.float()', 'ByteProperty': 'self.byte()', 'DoubleProperty': 'self.double()', 'Int16Property': 'self.i16()'}
PROP_VALUE_WRITER_CALLS = {'Int64Property': 'self.i64(value)', 'UInt64Property': 'self.u64(value)', 'UInt16Property': 'self.u16(value)', 'FixedPoint64Property': 'self.i32(value)', 'FloatProperty': 'self.float(value)', 'ByteProperty': 'self.byte(value)', 'DoubleProperty': 'self.double(value)', 'Int16Property': 'self.i16(value)'}
def handle_prop_value_fix(file_path, missing_type, changelog, dry_run):
    reader_call = PROP_VALUE_READER_CALLS.get(missing_type)
    writer_call = PROP_VALUE_WRITER_CALLS.get(missing_type)
    if not reader_call or not writer_call:
        return False
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    fixed = False
    reader_pattern = "        elif type_name == 'StrProperty':\n            return self.fstring()\n        else:\n            raise Exception(f'Unknown property value type: {type_name} ({path})')"
    reader_replacement = f"        elif type_name == 'StrProperty':\n            return self.fstring()\n        elif type_name == '{missing_type}':\n            return {reader_call}\n        else:\n            raise Exception(f'Unknown property value type: {{type_name}} ({{path}})')"
    if reader_pattern in content:
        if not dry_run:
            backup_file(file_path)
        content = content.replace(reader_pattern, reader_replacement)
        fixed = True
    writer_pattern = "        elif type_name == 'StrProperty':\n            self.fstring(value)\n        else:\n            raise Exception(f'Unknown property value type: {type_name}')"
    writer_replacement = f"        elif type_name == 'StrProperty':\n            self.fstring(value)\n        elif type_name == '{missing_type}':\n            {writer_call}\n        else:\n            raise Exception(f'Unknown property value type: {{type_name}}')"
    if writer_pattern in content:
        content = content.replace(writer_pattern, writer_replacement)
        fixed = True
    if fixed and (not dry_run):
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        changelog.record(file_path, f'Added {missing_type} to prop_value (reader + writer)')
    return fixed
def backup_file(file_path):
    bak = str(file_path) + '.bak'
    if not os.path.exists(bak):
        shutil.copy2(file_path, bak)
        return bak
    return None
def harden_all_modules(dry_run):
    changelog = ChangeLog()
    rawdata_dir = get_src_dir() / 'palsav' / 'palsav' / 'rawdata'
    py_files = sorted(rawdata_dir.glob('*.py'))
    match_based_encode_files = {'map_concrete_model_module.py', 'map_concrete_model.py', 'work.py'}
    for file_path in py_files:
        fname = file_path.name
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        eof_fixed = handle_eof_replacement(str(file_path), changelog, dry_run)
        encode_fixed = handle_encode_fix(str(file_path), fname in match_based_encode_files, changelog, dry_run)
    return changelog
def main():
    parser = argparse.ArgumentParser(description='Auto-update PalWorld Save Tools for new save formats.\nDetects structural changes in new .sav files and patches\nthe palsav source code to handle them.', formatter_class=argparse.RawDescriptionHelpFormatter, epilog=textwrap.dedent('            Examples:\n              python auto_update.py "BetaTestSave\\Level.sav"\n              python auto_update.py "BetaTestSave\\Level.sav" --dry-run\n              python auto_update.py "BetaTestSave\\Level.sav" --harden-only\n        '))
    parser.add_argument('filename', help='New-format .sav file to analyze')
    parser.add_argument('--dry-run', action='store_true', help='Show what would change without modifying files')
    parser.add_argument('--harden-only', action='store_true', help='Only harden rawdata modules against crashes (no iterative fix loop)')
    args = parser.parse_args()
    if not os.path.exists(args.filename):
        print(f'Error: {args.filename} does not exist')
        return 1
    print('PalWorld Save Tools - Auto-Update')
    print('=' * 60)
    print('\n[Phase 1/3] Hardening rawdata modules against structural changes...')
    harden_changelog = harden_all_modules(args.dry_run)
    harden_changelog.print_report()
    if args.harden_only:
        print('\nHarden-only mode. Skipping iterative fix loop.')
        return 0
    if args.dry_run:
        print('\nDry-run mode. Skipping iterative fix loop (no changes will be saved).')
        print('Re-run without --dry-run to apply fixes.')
        return 0
    print(f'\n[Phase 2/3] Iterative fix loop for {args.filename}...')
    success = False
    fix_changelog = ChangeLog()
    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f'\n  Iteration {iteration}: Attempting to parse save...')
        proc, _ = run_convert(args.filename)
        if proc.returncode == 0:
            print('  [OK] Save parses successfully!')
            success = True
            break
        error = parse_error(proc.stderr, proc.stdout)
        if error is None:
            print('  [FAIL] Could not parse error from output.')
            print(f"  STDERR:\n{textwrap.indent(proc.stderr[:2000], '    ')}")
            break
        print(f"  Error type: {error['type']}")
        print(f"  Message: {error['error_message']}")
        fixed = False
        if error['type'] in ('unknown_module_type', 'eof_not_reached'):
            file_line = error.get('file_line')
            if file_line:
                file_path, line_num = file_line
                if os.path.exists(file_path):
                    fixed = handle_eof_replacement(file_path, fix_changelog, args.dry_run)
                    if not fixed:
                        fixed = handle_encode_fix(file_path, False, fix_changelog, args.dry_run)
        if error['type'] == 'unknown_property_value_type':
            missing_type = error.get('missing_type')
            archive_path = get_src_dir() / 'palsav' / 'palsav' / 'archive.py'
            if missing_type and archive_path.exists():
                fixed = handle_prop_value_fix(str(archive_path), missing_type, fix_changelog, args.dry_run)
        if not fixed:
            print(f'  [FAIL] Could not auto-fix this error.')
            print(f'  Manual intervention may be needed.')
            break
    fix_changelog.print_report()
    print(f'\n[Phase 3/3] Verification...')
    if success:
        print('  Running round-trip verification...')
        rt_status, rt_msg = run_roundtrip(args.filename)
        if rt_status == 'ok':
            print('  [OK] Round-trip OK (original and resaved are identical)')
        elif rt_status == 'json_fail':
            print(f'  [FAIL] JSON conversion failed during round-trip')
        elif rt_status == 'sav_fail':
            print(f'  [FAIL] SAV conversion failed during round-trip')
        elif rt_status == 'mismatch':
            print('  [FAIL] Round-trip MISMATCH (original and resaved differ)')
        else:
            print(f'  Round-trip: {rt_status}')
    if success:
        print('\n[OK] Auto-update completed successfully!')
        print('  The save file can now be parsed with the updated tools.')
        return 0
    else:
        print('\n[FAIL] Auto-update did not complete successfully.')
        print('  Some errors may require manual fixes.')
        return 1
if __name__ == '__main__':
    main()