from collections import Counter
class ContainerOwnership:
    def __init__(self):
        self._instance_to_container = {}
        self._container_owners = {}
        self._instance_slot = {}
    @classmethod
    def build(cls, cmap, container_data):
        obj = cls()
        if not cmap or not container_data:
            return obj
        for entry in container_data:
            cid = entry.get('key', {}).get('ID', {}).get('value')
            if not cid:
                continue
            cid_key = obj._key(cid)
            slots_wrapper = entry.get('value', {}).get('Slots', {}).get('value', {})
            slots = slots_wrapper.get('values', []) if isinstance(slots_wrapper, dict) else []
            for se in slots:
                si_val = se.get('SlotIndex', {}).get('value', -1)
                raw_data = se.get('RawData', {}).get('value', {})
                inst_id = raw_data.get('instance_id', '')
                if inst_id and si_val >= 0:
                    inst_key = obj._key(inst_id)
                    obj._instance_to_container[inst_key] = cid_key
                    obj._instance_slot[inst_key] = si_val
        owner_votes = {}
        for item in cmap:
            inst_val = item.get('key', {}).get('InstanceId', {}).get('value')
            if not inst_val:
                continue
            inst_key = obj._key(inst_val)
            container_id = obj._instance_to_container.get(inst_key)
            if not container_id:
                continue
            try:
                raw = item.get('value', {}).get('RawData', {}).get('value', {})
                if not raw:
                    continue
                raw = raw.get('object', {}).get('SaveParameter', {}).get('value', {})
                if not raw:
                    continue
                owner = raw.get('OwnerPlayerUId', {}).get('value')
                if owner:
                    owner_key = obj._key(owner)
                    if container_id not in owner_votes:
                        owner_votes[container_id] = Counter()
                    owner_votes[container_id][owner_key] += 1
            except Exception:
                continue
        for cid, votes in owner_votes.items():
            if votes:
                obj._container_owners[cid] = votes.most_common(1)[0][0]
        return obj
    def get_container(self, instance_id):
        return self._instance_to_container.get(self._key(instance_id))
    def get_slot_index(self, instance_id):
        return self._instance_slot.get(self._key(instance_id))
    def get_container_owner(self, container_id):
        return self._container_owners.get(self._key(container_id))
    def belongs_to_player(self, instance_id, owner_uid, player_uid):
        player_key = self._key(player_uid)
        if not player_key:
            return False
        return self.get_effective_owner(instance_id, owner_uid) == player_key
    def get_effective_owner(self, instance_id, fallback_owner=None):
        inst_key = self._key(instance_id)
        container_id = self._instance_to_container.get(inst_key)
        if container_id:
            container_owner = self._container_owners.get(container_id)
            if container_owner:
                return container_owner
        return self._key(fallback_owner)
    def player_owns_container(self, container_id, player_uid):
        owner = self._container_owners.get(self._key(container_id))
        return bool(owner and owner == self._key(player_uid))
    @staticmethod
    def _key(uid):
        if uid is None:
            return ''
        if isinstance(uid, dict):
            uid = uid.get('value', '')
        return str(uid).replace('-', '').lower()