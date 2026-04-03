import os
import asyncio
from config import CHANNELS

class Reader():
    def __init__(self):
        self._channels_entities = []
        self._lock = asyncio.Lock()  # Блокировка для исключения параллельного доступа

    def get_chat_ids(self):
        return [data[2] for data in self._channels_entities]

    def get_channels_ids(self):
        return [data[1] for data in self._channels_entities]

    def get_channel_entity_for_id(self, channel_id: int):
        return [data[0] for data in self._channels_entities if data[1] == channel_id].pop()

    def get_channel_settings_for_id(self, channel_id: int):
        entity = self.get_channel_entity_for_id(channel_id)
        for ch in CHANNELS:
            if ch['channel'] == entity:
                return ch

    def get_channels_entities_from_file(self):
        return [channel['channel'] for channel in CHANNELS]

    def get_chat_id_for_channel(self,channel_id: int):
        for channel_data in self._channels_entities:
            if channel_data[1] == channel_id:
                return channel_data[2]

    def write_channel_id_uniq(self, entity: str, channel_id: int):
        data = (entity,channel_id)
        if data not in self._channels_entities:
            self._channels_entities.append(
                data
            )