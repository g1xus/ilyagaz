from telethon.tl.types import MessageEntityCustomEmoji

# Patch Telethon to gracefully skip unknown Telegram API constructor IDs
# (e.g. dialogFilterChatlist 0x1c32b11c added in newer Telegram layers).
# Without this patch, Telethon catches TypeNotFoundError in updates.py
# and calls disconnect(), killing the client silently.
from telethon.extensions.binaryreader import BinaryReader as _BinaryReader
from telethon.errors.common import TypeNotFoundError as _TypeNotFoundError
_orig_tgread_object = _BinaryReader.tgread_object
def _safe_tgread_object(self):
    try:
        return _orig_tgread_object(self)
    except _TypeNotFoundError:
        return None
_BinaryReader.tgread_object = _safe_tgread_object

from reader import Reader
import os
import json
from my_session import MySession,ScheduleReaction
from loguru import logger
from typing import List
from telethon import events,TelegramClient
from telethon.types import Message
import asyncio
import config
import random
from datetime import datetime,timedelta
from telethon.errors import ChannelPrivateError
import re
from telethon import utils as tg_utils
from contextlib import suppress

SUBSCRIBE_CACHE_PATH = os.path.join('data', 'subscribed_cache.json')

def _load_subscribe_cache() -> dict:
    try:
        with open(SUBSCRIBE_CACHE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_subscribe_cache(cache: dict):
    os.makedirs('data', exist_ok=True)
    with open(SUBSCRIBE_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def _is_cached(cache: dict, session_name: str, channel: str) -> bool:
    return channel in cache.get(session_name, [])

def _mark_cached(cache: dict, session_name: str, channel: str):
    cache.setdefault(session_name, [])
    if channel not in cache[session_name]:
        cache[session_name].append(channel)

reader = Reader()

def extract_emojis_from_message(event, allowed_emoji):
    emojis = []

    # Premium emojis
    if event.message.entities:
        premium = [
            reaction.document_id
            for reaction in event.message.entities
            if isinstance(reaction, MessageEntityCustomEmoji)
        ]
        emojis += [e for e in premium if e in allowed_emoji]

    # Unicode emojis
    for emoji in allowed_emoji:
        if str(emoji) in event.message.text:
            emojis.append(emoji)

    return emojis

async def subscribe_to_channels(sessions: List[MySession]):
    cache = _load_subscribe_cache()
    cache_dirty = False

    for channel in reader.get_channels_entities_from_file():
        # Подписываем КАЖДУЮ сессию на канал, чтобы у всех был entity/access_hash в кеше
        # (иначе Telethon не сможет отправить реакцию по одному лишь channel_id).
        channel_id = None
        ok = 0
        had_network_calls = False
        random.shuffle(sessions)
        for session in sessions:
            if _is_cached(cache, session.session_name, channel):
                logger.info(f"[{session.session_name}] Канал {channel} уже в кеше, пропускаю проверку")
                ok += 1
                continue

            had_network_calls = True
            cid = await session.get_channel_id(channel)
            if not cid:
                cid = await session.subscribe_to_channel(channel)

            logger.info(f"[{session.session_name}] Полученая Дата канала: {cid}")
            if cid and channel_id is None:
                channel_id = cid
            if cid:
                ok += 1
                _mark_cached(cache, session.session_name, channel)
                cache_dirty = True

        # Если все сессии отработали успешно, записываем данные канала
        reader.write_channel_id_uniq(channel,channel_id)
        logger.info(f"Канал {channel}: подписано/валидно {ok}/{len(sessions)} сессий, channel_id={channel_id}")

        # Задержка между каналами только если были реальные сетевые проверки
        if had_network_calls:
            sleep_time = 1
            logger.info(f"Ожидаю {sleep_time} сек для получения ID следующего канала")
            await asyncio.sleep(sleep_time)

    if cache_dirty:
        _save_subscribe_cache(cache)

async def validate_sessions(sessions: List[MySession]):
    logger.info("Запуск валидации")
    res = []
    for session in sessions:
        client = await session.get_client(update=True)
        if client:
            res.append(session)
        else:
            logger.warning(f"Сессия {session.session_name} мертва. Удаляю файл сессии.")
            try:
                os.remove(session.session_name)
            except Exception as e:
                logger.error(f"Не удалось удалить файл сессии {session.session_name}: {e}")
    return res


async def schedule_reactions(sessions: List[MySession], settings: dict, channel_id: int, post_id: int, post_premium_emoji: List[int]):
    
    channel_identifier = settings.get('channel')

    # 1. Распределяем реакции по сессиям
    # Копируем проценты реакций
    base_reactions = settings['reactions'].copy()
    reactions_count = settings['count']
    sessions = sessions[0:reactions_count]
    total_sessions = len(sessions)
    # Проверяем премиум реакции
    affected_reactions = []
    for reaction, new_percent in settings.get('post_reactions', {}).items():
        if reaction in post_premium_emoji:
            affected_reactions.append((reaction, new_percent))

    if affected_reactions:
        # Если есть реакции, которые должны получить новый процент
        # Шаг 1: обнуляем и заменяем проценты для затронутых реакций
        updated_reactions = {}
        replaced_total = 0
        for reaction, new_percent in affected_reactions:
            updated_reactions[reaction] = new_percent
            replaced_total += new_percent

        # Остаток процентов, который нужно раскидать на остальные реакции
        leftover = 100 - replaced_total

        # Остальные реакции (те, что не были затронуты)
        other_reactions = {r: p for r, p in base_reactions.items() if r not in updated_reactions}

        if other_reactions:
            old_sum = sum(other_reactions.values())

            # Пропорционально перераспределяем остаток
            for r, old_p in other_reactions.items():
                updated_reactions[r] = leftover * (old_p / old_sum)
        else:
            # Если других реакций нет — просто оставляем 100% как есть
            pass

        final_reactions = updated_reactions
    else:
        # Ничего не меняем
        final_reactions = base_reactions

    # Генерация списка реакций под количество сессий
    reaction_assignments = []
    for reaction, percent in final_reactions.items():
        count = int(total_sessions * percent / 100)
        reaction_assignments.extend([reaction] * count)


    # Если получилось меньше, чем общее число сессий – добавляем случайные реакции
    while len(reaction_assignments) < total_sessions:
        reaction_assignments.append(random.choice(list(settings['reactions'].keys())))
    # Перемешиваем, чтобы распределение было случайным
    random.shuffle(reaction_assignments)

    # 2. Распределяем временные интервалы по сессиям
    time_assignments = []
    for minute, percent in settings['time'].items():
        count = int(total_sessions * percent / 100)
        time_assignments.extend([minute] * count)
    while len(time_assignments) < total_sessions:
        time_assignments.append(random.choice(list(settings['time'].keys())))
    random.shuffle(time_assignments)

    # 3. Планируем отложенные реакции для каждой сессии
    tasks = []
    for i, session in enumerate(sessions):
        reaction = reaction_assignments[i]
        minute = time_assignments[i]
        max_seconds = minute * 60
        delay = int(random.uniform(0, max_seconds))

        logger.info(f"Сессия {session.session_name} отправит реакцию {reaction} через {delay:.2f} секунд")
        reaction = ScheduleReaction(channel_identifier, channel_id, post_id, reaction, delay)
        tasks.append(
            session.schedule_reaction(reaction)
        )

    await asyncio.gather(*tasks)

async def main():
    sessions: List[MySession] = []
    all_sessions: List[MySession] = []

    try:
        # Берем все сессии
        for session_file in os.listdir('sessions'):
            if not session_file.endswith('.session'):
                continue
            session = MySession(os.path.join('sessions',session_file))
            sessions.append(session)
        all_sessions = list(sessions)

        if not sessions:
            logger.error("В папке sessions не найдено ни одной .session сессии. Завершаю запуск.")
            return

        # Валидирум сессии
        sessions = await validate_sessions(sessions)
        if not sessions:
            logger.error("После валидации не осталось рабочих сессий. Завершаю запуск.")
            return

        # Подписываем их на каналы
        await subscribe_to_channels(sessions)

        # Берем главную сессию и пускаем на ней пул
        main_session: MySession = next((session for session in sessions if 'main' in session.session_name), None)
        if main_session is None:
            main_session = sessions[0]

        sessions.remove(main_session)
        main_clinet = await main_session.get_client()
        if not main_clinet:
            logger.error(f"Не удалось запустить главную сессию {main_session.session_name}. Завершаю запуск.")
            return
        logger.info(f"Главная сессия: {main_session.session_name}")

        # Собираем чаты из config (инвайт/username/ID) и маппим настройки на chat_id
        channel_identifiers = reader.get_channels_entities_from_file()
        resolved_chats = []
        settings_by_chat_id = {}
        for ident in channel_identifiers:
            try:
                peer = await main_clinet.get_input_entity(ident)
                if peer is None:
                    continue
                resolved_chats.append(peer)

                chat_id = tg_utils.get_peer_id(peer)
                settings_by_chat_id[chat_id] = next(
                    (ch for ch in config.CHANNELS if ch.get('channel') == ident),
                    None
                )
            except Exception as e:
                logger.warning(f"Канал {ident} не удалось разрешить, пропускаю: {e}")

        # Декоратор для обработки новых сообщений
        @main_clinet.on(events.NewMessage(chats=resolved_chats))
        async def message_handler(event: events.NewMessage.Event):
            settings = settings_by_chat_id.get(event.chat_id)
            if not settings:
                return

            logger.info(f"Новое сообщение в {event.chat.title}: {event.raw_text} с ID: {event.message.id}")
            allowed = settings['post_reactions'].keys()
            emoji = extract_emojis_from_message(event, allowed)

            # Создаем шедул на все сессии
            asyncio.create_task(schedule_reactions(sessions, settings, event.chat_id, event.message.id, emoji))

        logger.info(f"Процесс автокоментинга запущен на {len(sessions)} сессиях и {len(resolved_chats)} каналах")
        await main_clinet.run_until_disconnected()
    finally:
        # Чисто закрываем все поднятые клиенты до закрытия event loop.
        for session in all_sessions:
            if session.client:
                with suppress(Exception):
                    await session.client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())