import os
import sys
import argparse


def _ensure_package_path():
    _script = os.path.abspath(__file__)
    _pkg = os.path.dirname(os.path.dirname(_script))
    _src = os.path.dirname(_pkg)
    for p in (_src, _pkg):
        if p not in sys.path:
            sys.path.insert(0, p)

def main():
    if os.environ.get('PYTHONHASHSEED', 'random') != '0':
        os.environ['PYTHONHASHSEED'] = '0'
        if os.name != 'nt' and hasattr(os, 'execv'):
            os.execv(sys.argv[0], sys.argv)
        else:
            import subprocess
            sys.exit(subprocess.run([sys.executable, *sys.argv], env=os.environ).returncode)

    commands = {
        "convert": ("palsav.commands.convert", "Convert save files between .sav and .json"),
        "backup": ("palsav.commands.backup", "Backup and restore players and bases"),
        "diag": ("palsav.commands.diag", "Read-only save diagnostics"),
        "validate": ("palsav.commands.roundtrip_validation", "Roundtrip integrity validation tests"),
    }

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("usage: palsav [-h] <command> [<args>]\n")
        print("Available commands:\n")
        for name, (_, desc) in sorted(commands.items()):
            print(f"  {name:<12} {desc}")
        print()
        print("Run 'palsav <command> --help' for more information.")
        sys.exit(0)

    if sys.argv[1] not in commands:
        sys.argv.insert(1, "convert")

    subcommand = sys.argv.pop(1)
    if subcommand == 'convert':
        if len(sys.argv) > 2 and not sys.argv[2].startswith('-'):
            output_path = sys.argv.pop(2)
            sys.argv[2:2] = ['--force', '--output', output_path]
    module_path, _ = commands[subcommand]
    __import__(module_path)
    module = sys.modules[module_path]
    module.main()


if __name__ == "__main__":
    _ensure_package_path()
    main()
