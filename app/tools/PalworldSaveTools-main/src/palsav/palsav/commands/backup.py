import argparse
import logging
import os
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)
def main():
    parser = argparse.ArgumentParser(prog='palsav backup', description='Backup and restore Palworld players and bases')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    export_player_parser = subparsers.add_parser('export-player', help='Export player backup')
    export_player_parser.add_argument('level_sav', help='Path to Level.sav')
    export_player_parser.add_argument('player_uid', help='Player UID')
    export_player_parser.add_argument('-o', '--output', required=True, help='Output path (.player.pstz)')
    export_player_parser.add_argument('--no-compress', action='store_true', help='Export as uncompressed JSON instead of OOZ compressed')
    export_player_parser.add_argument('-f', '--force', action='store_true', help='Force overwrite output file')
    export_base_parser = subparsers.add_parser('export-base', help='Export base backup')
    export_base_parser.add_argument('level_sav', help='Path to Level.sav')
    export_base_parser.add_argument('base_id', help='Base ID')
    export_base_parser.add_argument('-o', '--output', required=True, help='Output path (.base.pstz or .json)')
    export_base_parser.add_argument('--no-compress', action='store_true', help='Export as uncompressed JSON instead of OOZ compressed')
    export_base_parser.add_argument('-f', '--force', action='store_true', help='Force overwrite output file')
    import_player_parser = subparsers.add_parser('import-player', help='Import player backup')
    import_player_parser.add_argument('backup', help='Path to player backup file (.player.pstz)')
    import_player_parser.add_argument('level_sav', help='Path to target Level.sav')
    import_player_parser.add_argument('players_folder', help='Path to Players folder')
    import_player_parser.add_argument('--no-compress', action='store_true', help='Backup is uncompressed JSON')
    import_base_parser = subparsers.add_parser('import-base', help='Import base backup')
    import_base_parser.add_argument('backup', help='Path to base backup file (.base.pstz or .json)')
    import_base_parser.add_argument('level_sav', help='Path to target Level.sav')
    import_base_parser.add_argument('guild_id', help='Target guild ID')
    import_base_parser.add_argument('--no-compress', action='store_true', help='Backup is uncompressed JSON')
    import_base_parser.add_argument('--offset', nargs=3, type=int, default=[8000, 0, 0], help='Base offset (x y z)')
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        exit(1)
    compressed = not args.__dict__.get('no_compress', False)
    if args.command == 'export-player':
        from palworld_aio.managers.backup_manager import export_player_backup
        if os.path.exists(args.output) and (not args.force):
            logger.error(f'Output file {args.output} already exists. Use -f to overwrite.')
            exit(1)
        try:
            export_player_backup(args.level_sav, args.player_uid, args.output, compressed=compressed)
            logger.info(f'Player backup exported to {args.output}')
        except Exception as e:
            logger.error(f'Failed to export player: {e}')
            exit(1)
    elif args.command == 'export-base':
        from palworld_aio.managers.backup_manager import export_base_backup
        if os.path.exists(args.output) and (not args.force):
            logger.error(f'Output file {args.output} already exists. Use -f to overwrite.')
            exit(1)
        try:
            export_base_backup(args.level_sav, args.base_id, args.output, compressed=compressed)
            logger.info(f'Base backup exported to {args.output}')
        except Exception as e:
            logger.error(f'Failed to export base: {e}')
            exit(1)
    elif args.command == 'import-player':
        from palworld_aio.managers.backup_manager import import_player_backup
        try:
            import_player_backup(args.backup, args.level_sav, args.players_folder, compressed=compressed)
            logger.info(f'Player backup imported to {args.level_sav}')
        except Exception as e:
            logger.error(f'Failed to import player: {e}')
            exit(1)
    elif args.command == 'import-base':
        from palworld_aio.managers.backup_manager import import_base_backup
        offset = tuple(args.offset)
        try:
            import_base_backup(args.backup, args.level_sav, args.guild_id, compressed=compressed, offset=offset)
            logger.info(f'Base backup imported to {args.level_sav}')
        except Exception as e:
            logger.error(f'Failed to import base: {e}')
            exit(1)
if __name__ == '__main__':
    main()