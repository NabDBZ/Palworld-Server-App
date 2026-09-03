import argparse
import contextlib
import gc
import sys
import time
import os
import logging
logger = logging.getLogger(__name__)
from palsav import setup_logging
from palsav.gvas import GvasFile
from palsav import json_tools
from palsav.core import compress_gvas_to_sav, decompress_sav_to_gvas
from palsav.paltypes import DISABLED_PROPERTIES, PALWORLD_CUSTOM_PROPERTIES, PALWORLD_TYPE_HINTS
@contextlib.contextmanager
def _gc_paused():
    was_enabled = gc.isenabled()
    if was_enabled:
        gc.disable()
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()
            gc.collect()
def main():
    parser = argparse.ArgumentParser(prog='palworld-save-tools', description='Converts Palworld save files to and from JSON')
    parser.add_argument('filename')
    parser.add_argument('--to-json', action='store_true', help='Override heuristics and convert SAV file to JSON')
    parser.add_argument('--from-json', action='store_true', help='Override heuristics and convert JSON file to SAV')
    parser.add_argument('--output', '-o', help='Output file (default: <filename>.json or <filename>.sav)')
    parser.add_argument('--force', '-f', action='store_true', help='Force overwriting output file if it already exists without prompting')
    parser.add_argument('--library', '-l', choices=['zlib', 'palooz'], default='palooz', help="Compression library used to convert JSON files to SAV files. 'zlib' for zlib compression, 'palooz' for palooz compression (default: palooz)")
    parser.add_argument('--convert-nan-to-null', action='store_true', help='Convert NaN/Inf/-Inf floats to null when converting from SAV to JSON. This will lose information in the event Inf/-Inf is in the sav file (default: false)')
    parser.add_argument('--custom-properties', default=','.join(set(PALWORLD_CUSTOM_PROPERTIES.keys()) - DISABLED_PROPERTIES), type=lambda t: [s.strip() for s in t.split(',')], help="Comma-separated list of custom properties to decode, or 'all' for all known properties. This can be used to speed up processing by excluding properties that are not of interest. (default: all)")
    parser.add_argument('--minify-json', action='store_true', help='Minify JSON output')
    parser.add_argument('--raw', action='store_true', help='Output raw GVAS file')
    parser.add_argument('--resave', action='store_true', help='Load SAV and resave as SAV (no JSON). Useful for benchmarking the load/write cycle.')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--debug-log', action='store_true', help='Enable debug logging to file')
    args = parser.parse_args()
    setup_logging(debug=args.debug, debug_log=args.debug_log)
    if args.to_json and args.from_json:
        logger.error('Cannot specify both --to-json and --from-json')
        exit(1)
    if args.resave and args.to_json:
        logger.error('Cannot specify both --resave and --to-json')
        exit(1)
    if args.resave and args.from_json:
        logger.error('Cannot specify both --resave and --from-json')
        exit(1)
    if not os.path.exists(args.filename):
        logger.error(f'{args.filename} does not exist')
        exit(1)
    if not os.path.isfile(args.filename):
        logger.error(f'{args.filename} is not a file')
        exit(1)
    if args.resave:
        if not args.output:
            output_path = args.filename + '.resave.sav'
        else:
            output_path = args.output
        resave_sav(args.filename, output_path, force=args.force, custom_properties_keys=args.custom_properties)
    elif args.to_json or args.filename.endswith('.sav'):
        if not args.output:
            output_path = args.filename + '.json'
        else:
            output_path = args.output
        convert_sav_to_json(args.filename, output_path, force=args.force, minify=args.minify_json, allow_nan=not args.convert_nan_to_null, custom_properties_keys=args.custom_properties, raw=args.raw)
    if args.from_json or args.filename.endswith('.json'):
        if not args.output:
            output_path = args.filename.replace('.json', '')
        else:
            output_path = args.output
        convert_json_to_sav(args.filename, output_path, force=args.force, zlib=args.library == 'zlib')
def resave_sav(filename, output_path, force=False, custom_properties_keys=['all']):
    from palsav.io import load_sav, save_sav
    logger.info(f'Loading SAV file {filename}')
    custom_properties = {}
    if len(custom_properties_keys) > 0 and custom_properties_keys[0] == 'all':
        custom_properties = PALWORLD_CUSTOM_PROPERTIES
    else:
        for prop in PALWORLD_CUSTOM_PROPERTIES:
            if prop in custom_properties_keys:
                custom_properties[prop] = PALWORLD_CUSTOM_PROPERTIES[prop]
    with _gc_paused():
        gvas_file = load_sav(filename, custom_properties=custom_properties)
    logger.info(f'Writing SAV file to {output_path}')
    if os.path.exists(output_path):
        if not force:
            if not confirm_prompt(f'{output_path} already exists. Overwrite?'):
                exit(1)
    with _gc_paused():
        save_sav(gvas_file, output_path)
def convert_sav_to_json(filename, output_path, force=False, minify=False, allow_nan=True, custom_properties_keys=['all'], raw=False):
    from palsav.io import load_sav
    start_time = time.perf_counter()
    logger.info(f'Converting {filename} to JSON, saving to {output_path}')
    if os.path.exists(output_path):
        logger.debug(f'{output_path} already exists, this will overwrite the file')
        if not force:
            if not confirm_prompt('Are you sure you want to continue?'):
                exit(1)
    if raw:
        with open(filename, 'rb') as f:
            data = f.read()
        from palsav.core import decompress_sav_to_gvas
        raw_gvas, _ = decompress_sav_to_gvas(data)
        output_dir = os.path.dirname(output_path)
        output_file = f'{os.path.basename(output_path)}.bin'
        output_file_path = os.path.join(output_dir, output_file)
        logger.info(f'Writing raw GVAS file to {output_file_path}')
        with open(output_file_path, 'wb') as f:
            f.write(raw_gvas)
    logger.info('Loading GVAS file')
    custom_properties = {}
    if len(custom_properties_keys) > 0 and custom_properties_keys[0] == 'all':
        custom_properties = PALWORLD_CUSTOM_PROPERTIES
    else:
        for prop in PALWORLD_CUSTOM_PROPERTIES:
            if prop in custom_properties_keys:
                custom_properties[prop] = PALWORLD_CUSTOM_PROPERTIES[prop]
    with _gc_paused():
        gvas_file = load_sav(filename, custom_properties=custom_properties, allow_nan=allow_nan)
    gvas_parse_time = time.perf_counter()
    logger.info(f'GVAS file loaded in {gvas_parse_time - start_time:.2f} seconds')
    logger.info(f'Writing JSON to {output_path}')
    write_start_time = time.perf_counter()
    json_tools.dump(gvas_file.dump(), output_path, minify=minify, allow_nan=allow_nan)
    write_end_time = time.perf_counter()
    logger.info(f'JSON written in {write_end_time - write_start_time:.2f} seconds')
    end_time = time.perf_counter()
    logger.info(f'Conversion took {end_time - start_time:.2f} seconds')
def convert_json_to_sav(filename, output_path, force=False, zlib=False):
    from palsav.io import save_sav
    logger.info(f'Converting {filename} to SAV, saving to {output_path}')
    if os.path.exists(output_path):
        logger.debug(f'{output_path} already exists, this will overwrite the file')
        if not force:
            if not confirm_prompt('Are you sure you want to continue?'):
                exit(1)
    logger.info(f'Loading JSON from {filename}')
    data = json_tools.load(filename)
    gvas_file = GvasFile.load(data)
    logger.info('Compressing SAV file')
    save_type = 50 if zlib else None
    with _gc_paused():
        save_sav(gvas_file, output_path, save_type=save_type)
def confirm_prompt(question: str) -> bool:
    reply = None
    while reply not in ('y', 'n'):
        reply = input(f'{question} (y/n): ').casefold()
    return reply == 'y'
if __name__ == '__main__':
    main()