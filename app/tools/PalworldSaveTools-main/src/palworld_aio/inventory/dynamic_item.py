import uuid
from typing import Any, Dict, Optional
from palsav.archive import UUID
from palworld_aio.inventory.dynamic_item_manager import as_uuid, are_equal_uuids
class DynamicItem:
    def __init__(self, local_id: UUID, dynamic_item_save_data: Dict[str, Any]=None):
        self.local_id = local_id
        self.save_data = dynamic_item_save_data or self._create_default_save_data()
    def _create_default_save_data(self) -> Dict[str, Any]:
        return {'RawData': {'type': 'Array', 'value': {'type': 'Byte', 'values': {'created_world_id': '00000000-0000-0000-0000-000000000000', 'local_id_in_created_world': str(self.local_id), 'trailing_bytes': [0] * 16}}}, 'CustomVersionData': {'array_type': 'ByteProperty', 'id': None, 'value': {'values': [1, 0, 0, 0, 126, 180, 234, 18, 154, 27, 90, 255, 113, 170, 113, 188, 223, 51, 214, 14, 1, 0, 0, 0]}, 'type': 'ArrayProperty'}}
    def update_from(self, other_data: Dict[str, Any]) -> None:
        if 'created_world_id' in other_data:
            self.save_data['RawData']['value']['values']['created_world_id'] = other_data['created_world_id']
        if 'local_id_in_created_world' in other_data:
            self.save_data['RawData']['value']['values']['local_id_in_created_world'] = other_data['local_id_in_created_world']
    def get_static_id(self) -> str:
        return self.save_data.get('RawData', {}).get('value', {}).get('values', {}).get('static_id', '')
    def set_static_id(self, static_id: str) -> None:
        if 'RawData' not in self.save_data:
            self.save_data['RawData'] = {'type': 'Array', 'value': {'type': 'Byte', 'values': {}}}
        self.save_data['RawData']['value']['values']['static_id'] = static_id
    def get_count(self) -> int:
        return self.save_data.get('RawData', {}).get('value', {}).get('values', {}).get('count', 0)
    def set_count(self, count: int) -> None:
        if 'RawData' not in self.save_data:
            self.save_data['RawData'] = {'type': 'Array', 'value': {'type': 'Byte', 'values': {}}}
        self.save_data['RawData']['value']['values']['count'] = count
def generate_dynamic_item_uuids() -> Dict[str, str]:
    return {'created_world_id': str(uuid.uuid4()), 'local_id_in_created_world': str(uuid.uuid4())}
def sync_dynamic_items_with_registry(containers: Dict[str, Any]) -> bool:
    try:
        from palworld_aio.inventory.dynamic_item_manager import get_dynamic_item_manager
        from palworld_aio import constants
        dynamic_manager = get_dynamic_item_manager()
        if not constants.loaded_level_json:
            return False
        wsd = constants.loaded_level_json.get('properties', {}).get('worldSaveData', {}).get('value', {})
        if 'DynamicItemSaveData' not in wsd:
            wsd['DynamicItemSaveData'] = {'id': None, 'value': {'values': []}, 'type': 'ArrayProperty', 'custom_type': '.worldSaveData.DynamicItemSaveData'}
        dynamic_items = wsd.get('DynamicItemSaveData', {}).get('value', {}).get('values', [])
        referenced_dynamic_ids = set()
        for container_type, container in containers.items():
            if hasattr(container, '_standardized_container'):
                items = container._standardized_container.get_items()
                for item in items:
                    dynamic_id = item.get('dynamic_id')
                    if dynamic_id and dynamic_id != '00000000-0000-0000-0000-000000000000':
                        referenced_dynamic_ids.add(dynamic_id)
        for container_type, container in containers.items():
            if hasattr(container, '_standardized_container'):
                items = container._standardized_container.get_items()
                for item in items:
                    dynamic_id_str = item.get('dynamic_id')
                    if dynamic_id_str and dynamic_id_str != '00000000-0000-0000-0000-000000000000':
                        try:
                            dynamic_id = as_uuid(dynamic_id_str)
                            if dynamic_id and (not dynamic_manager.is_item_registered(dynamic_id)):
                                item_id = item.get('item_id', '')
                                container_id = container.container_id
                                dynamic_manager.register_item(item_id, container_id, dynamic_id)
                        except Exception as e:
                            pass
        # Only remove dynamics referenced by the current containers, preserve all others
        if referenced_dynamic_ids:
            _rem = {str(k).lower() for k in referenced_dynamic_ids}
            dynamic_items[:] = [
                d for d in dynamic_items
                if str(d.get('RawData', {}).get('value', {}).get('id', {}).get('local_id_in_created_world', '')).lower() not in _rem
            ]
        else:
            dynamic_items.clear()
        registry_items = dynamic_manager.registry._items
        for dynamic_id, item_data in registry_items.items():
            dynamic_items.append(item_data)
        return True
    except Exception as e:
        import traceback
        traceback.print_exc()
        return False