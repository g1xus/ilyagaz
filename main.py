from telethon.tl.types import MessageEntityCustomEmoji

from reader import Reader
import os
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
    for channel in reader.get_channels_entities_from_file():
        # Переменные для хранения channel_id и chat_id (возьмём из последней успешно обработавшей сессии)
        channel_id = None
        random.shuffle(sessions)
        for session in sessions:
            channel_data = await session.get_channel_id(channel)
            # Если нет данных, пробуем подписаться
            if not channel_data:
                channel_data = await session.subscribe_to_channel(channel)
            logger.info(f"Полученая Дата канала: {channel_data}")

            # Если так и не получилось получить данные — прерываемся
            if not channel_data:
                #logger.warning(f"Канал {channel} был пропущен (одна из сессий не смогла получить доступ)")
                continue

            # Распаковываем результаты
            _channel_id = channel_data
            if not _channel_id:
                logger.warning(f"Сессия не вернула ID канала или чата для {channel}.")
                continue

            # Если всё ок — обновим наши переменные
            channel_id = _channel_id
            break

        # Если все сессии отработали успешно, записываем данные канала
        reader.write_channel_id_uniq(channel,channel_id)

        # Задержка между каждым каналом, если на него все подписались
        sleep_time = 1
        logger.info(f"Ожидаю {sleep_time} сек для получения ID следующего канала")
        await asyncio.sleep(sleep_time)

async def validate_sessions(sessions: List[MySession]):
    logger.info("Запуск валидации")
    res = []
    for session in sessions:
        client = await session.get_client(update=True)
        if client:
            res.append(session)
        else:
            logger.warning(f"Сессия {session.session_name} мертва. Она не будет учавстовать в коментинге")
    return res


async def schedule_reactions(sessions: List[MySession], channel_id: int, post_id: int, post_premium_emoji: List[int]):
    total_sessions = len(sessions)
    settings = reader.get_channel_settings_for_id(channel_id)

    # 1. Распределяем реакции по сессиям
    # Копируем проценты реакций
    base_reactions = settings['reactions'].copy()

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
        reaction = ScheduleReaction(channel_id,post_id,reaction,delay)
        tasks.append(
            session.schedule_reaction(reaction)
        )

    await asyncio.gather(*tasks)

async def main():
    sessions: List[MySession] = []

    # Берем все сессии
    for session_file in os.listdir('sessions'):
        if not session_file.endswith('.session'):
            continue
        session = MySession(os.path.join('sessions',session_file))
        sessions.append(session)

    # Валидирум сессии
    sessions = await validate_sessions(sessions)
    # Подписываем их на каналы
    await subscribe_to_channels(sessions)

    # Берем главную сессию и пускаем на ней пул
    main_session: MySession = next(
        (session for session in sessions if 'main' in session.session_name),
        sessions[0]
    )
    sessions.remove(main_session)
    main_clinet = await main_session.get_client()
    logger.info(f"Главная сессия: {main_session.session_name}")


    # Декоратор для обработки новых сообщений
    @main_clinet.on(events.NewMessage(chats=reader.get_channels_ids()))
    async def message_handler(event: events.NewMessage.Event):
        logger.info(f"Новое сообщение в {event.chat.title}: {event.raw_text} с ID: {event.message.id}")
        allowed = reader.get_channel_settings_for_id(event.chat_id)['post_reactions'].keys()
        emoji = extract_emojis_from_message(event, allowed)

        # Создаем шедул на все сессии
        asyncio.create_task(schedule_reactions(sessions,event.chat_id,event.message.id, emoji))

    logger.info(f"Процесс автокоментинга запущен на {len(sessions)} сессиях и {len(reader.get_channels_ids())} каналах")
    await main_clinet.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())