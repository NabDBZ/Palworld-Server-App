import datetime, os, re, sys, uuid
from palworld_xgp_import.container_types import ContainerIndex, ContainerFileList, FILETIME, Container
from palworld_xgp_import.gamepass_manager import validate_steam_save
def create_container_entry(root, save_id, data, suffix):
    c_uuid = uuid.uuid4()
    f_uuid = uuid.uuid4()
    cdir = os.path.join(root, c_uuid.bytes_le.hex().upper())
    os.makedirs(cdir, exist_ok=True)
    with open(os.path.join(cdir, 'container.1'), 'wb') as f:
        f.write(4 .to_bytes(4, 'little'))
        f.write(1 .to_bytes(4, 'little'))
        name_bytes = 'Data'.encode('utf-16-le')
        f.write(name_bytes + b'\x00' * (128 - len(name_bytes)))
        f.write(b'\x00' * 16)
        f.write(f_uuid.bytes)
    with open(os.path.join(cdir, f_uuid.bytes_le.hex().upper()), 'wb') as f:
        f.write(data)
    return Container(container_name=f'{save_id}-{suffix}', cloud_id='', seq=1, flag=5, container_uuid=c_uuid, mtime=FILETIME.from_timestamp(datetime.datetime.now().timestamp()), size=len(data))
def main():
    if len(sys.argv) != 2:
        return
    steam = os.path.abspath(sys.argv[1])
    missing = validate_steam_save(steam)
    if missing:
        print(f'ERROR: Save is incomplete. Missing required files: {", ".join(missing)}')
        print('The game will not recognize this save without all required components.')
        return
    wgs = os.path.expandvars('%LOCALAPPDATA%\\Packages\\PocketpairInc.Palworld_ad4psfrxyesvt\\SystemAppData\\wgs')
    root = next((os.path.join(wgs, d) for d in os.listdir(wgs) if re.match('[0-9A-F]{16}_[0-9A-F]{32}$', d)))
    with open(os.path.join(root, 'containers.index'), 'rb') as f:
        idx = ContainerIndex.from_stream(f)
    print('Cleaning ghost entries...')
    idx.containers = [c for c in idx.containers if not c.container_name.startswith('EggTest')]
    new_id = uuid.uuid4().hex.upper()
    print(f'Creating new World ID: {new_id}')
    req = {'Level': 'Level.sav', 'LevelMeta': 'LevelMeta.sav', 'LocalData': 'LocalData.sav', 'WorldOption': 'WorldOption.sav'}
    for suffix, sfile in req.items():
        spath = os.path.join(steam, sfile)
        if os.path.exists(spath):
            print(f'Adding {suffix}...')
            idx.containers.append(create_container_entry(root, new_id, open(spath, 'rb').read(), suffix))
    pdir = os.path.join(steam, 'Players')
    if os.path.exists(pdir):
        for pf in os.listdir(pdir):
            if pf.endswith('.sav'):
                print(f'Adding Player {pf}...')
                pid = pf.replace('.sav', '')
                idx.containers.append(create_container_entry(root, new_id, open(os.path.join(pdir, pf), 'rb').read(), f'Players-{pid}'))
    idx.mtime = FILETIME.from_timestamp(datetime.datetime.now().timestamp())
    idx.write_file(root)
    print('Done.Launch game and look for the new world entry.')
if __name__ == '__main__':
    main()