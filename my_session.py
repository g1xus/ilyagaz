import traceback

from telethon import TelegramClient, events
from aiogram import types
from telethon.extensions.html import unparse as message_to_html
import re
from telethon import TelegramClient
from telethon.errors import InviteHashExpiredError, InviteHashInvalidError,UserAlreadyParticipantError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.channels import GetFullChannelRequest
from typing import Tuple, Optional
from loguru import logger
import asyncio
import aiofiles
import socks
import json
import os
import random
import config
from datetime import datetime,timedelta
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.functions.messages import SendReactionRequest
from telethon.errors.rpcerrorlist import UserNotParticipantError
from telethon import types
import logging
from telethon.network import ConnectionTcpIntermediate
from telethon.errors.rpcerrorlist import FloodWaitError
import functools

# Отключаем вывод сообщений от модулей Telethon, отвечающих за работу с соединением
logging.getLogger('telethon.network.mtprotosender').setLevel(logging.CRITICAL)
logging.getLogger('telethon.network.connection').setLevel(logging.CRITICAL)

def flood_wait_handler(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        while True:
            try:
                return await func(*args, **kwargs)
            except FloodWaitError as e:
                wait_time = e.seconds
                logger.warning(f"FloodWaitError: необходимо ждать {wait_time} секунд. Повторный запуск функции...")
                await asyncio.sleep(wait_time)
    return wrapper


class SessionFunctools:
    @staticmethod
    async def get_proxy():
        async with aiofiles.open(os.path.join('data','proxy.txt'), mode='r') as file:
            content = await file.readlines()
            if not content:
                return
            proxy_host, proxy_port, proxy_user, proxy_pass = random.choice(content).strip().split(':')

            return socks.SOCKS5, proxy_host, int(proxy_port), True, proxy_user, proxy_pass


class ScheduleReaction():
    def __init__(self, channel_id: int, post_id: int, reaction: str, delay: int):
        self.channel_id = channel_id
        self.post_id = post_id
        self.reaction = reaction
        self.delay = delay


class MySession(SessionFunctools):
    def __init__(self,session_name: str):
        self.proxy: Optional[tuple] = None
        self.session_name = session_name
        self.client: Optional[TelegramClient] = None

    async def get_client(self, update=False) -> Optional[TelegramClient]:
        """
        Инициализирует и возвращает TelegramClient.

        :param update: Если True, то создаёт новый клиент.
        :return: Экземпляр TelegramClient или None.
        """
        # Возвращаем клиент, если он уже инициализирован
        if self.client and not update:
            return self.client

        for _ in range(3):
            self.proxy = await self.get_proxy()

            self.client = TelegramClient(
                session=self.session_name,
                api_id=config.API_ID,
                api_hash=config.API_HASH,
                device_model="GU604VY-NM058WS",
                system_version="Windows 11",
                app_version="5.6.3 x64",
                lang_code='EN',
                system_lang_code='EN',
                proxy=self.proxy,
                connection=ConnectionTcpIntermediate,
                connection_retries=10,
                request_retries=5,
                timeout=45
            )
            try:
                await asyncio.wait_for(self.client.connect(), timeout=15)
                me = await self.client.get_me()
                if me is None:
                    logger.error(f"Сессия {self.session_name} мертва")
                    return
                logger.info(f"Подключен к сесcии {self.session_name} с прокси {self.proxy}")
                return self.client
            except asyncio.TimeoutError:
                logger.info(f"Ошибка при подключении к сессии {self.session_name} | Слишком долгое ожидание. Беру другое прокси")
            except BaseException as e:
                logger.info(f"Ошибка при подключении к сессии {self.session_name} | {e}. Пробую еще раз")
        # Если не вышло, то просто отключаемся
        await self.client.disconnect()

    async def subscribe_to_channel(self,channel_identifier: str) -> Optional[Tuple[int,int]]:
        """
        Подписывается на канал или чат по различным идентификаторам.

        :param client: Запущенный клиен
        :param channel_identifier: Идентификатор канала (ID, username, ссылка на вступление) или ChatID.
        :return: Кортеж (ID канала, имя канала) при успешной подписке или если пользователь уже подписан,
                 иначе None.
        """

        client = await self.get_client()

        if not client:
            logger.info(f"Не удалось запустить сессию '{client}'.")
            return None


        try:
            # Проверка, является ли идентификатор числом (ID канала или ChatID)
            if channel_identifier.isdigit():
                entity = await client.get_entity(int(channel_identifier))

            # Проверка, является ли идентификатор ссылкой на вступление
            elif re.match(r'https?://t\.me/\+[\w\d_-]+', channel_identifier) and "+" in channel_identifier:
                # Извлекаем хеш из ссылки
                hash_part = channel_identifier.split('/')[-1].replace('+', '')
                logger.info(f"Хеш для вступления: {hash_part}")
                try:
                    updates = await client(ImportChatInviteRequest(hash_part))
                    if updates.chats:
                        entity = updates.chats[0]
                    else:
                        logger.info("Не удалось получить чат после импорта ссылки.")
                        return None
                except InviteHashExpiredError:
                    logger.error("Ссылка для вступления истекла.")
                    return None
                except InviteHashInvalidError:
                    logger.error("Недействительная ссылка для вступления.")
                    return None
                except UserAlreadyParticipantError:
                    entity = await client.get_entity(channel_identifier)

            # Проверка, является ли идентификатор username (с или без @)
            else:
                username = channel_identifier.replace("https://t.me/","")
                username = username.lstrip('@')
                entity = await client.get_entity(username)


            # Проверка, уже ли пользователь подписан на канал или чат
            try:
                if hasattr(entity, 'megagroup') and entity.megagroup:
                    # Это супергруппа или чат
                    logger.info(f"Пользователь уже подписан на чат '{entity.title}' (ID: {entity.id}).")
                else:
                    # Это канал, пробуем присоединиться
                    await client(JoinChannelRequest(entity))
                    logger.info(f"Сессия '{self.session_name}' успешно подписалась на канал '{entity.title}' (ID: {entity.id}).")
            except Exception as join_error:
                # Предполагаем, что ошибка может означать, что пользователь уже подписан
                logger.warning(f"Возможно, пользователь уже подписан на '{entity.title}' (ID: {entity.id}): {join_error}")


            chat_data = await self.get_channel_id(entity)
            return chat_data
        except Exception as e:
            logger.error(f"Не удалось подписаться сессией '{self.session_name}' на '{channel_identifier}': {e}")
            return None

    async def get_channel_id(self, entity) -> Optional[tuple]:
        try:
            client = await self.get_client()
            full_channel_info = await client(GetFullChannelRequest(entity))
            full_channel = full_channel_info.full_chat
            channel_id = full_channel.id

            channel_id = (int(str(-100) + str(channel_id)))

            # Если пользователя нет в канале, все равно возвращаем None
            if not (await self.is_user_in_channel(channel_id)):
                return

            return channel_id
        except Exception as e:
            pass

    async def is_user_in_channel(self, channel):
        """
        Проверяет, является ли пользователь участником канала.

        :param client: экземпляр клиента Telethon.
        :param channel: канал (может быть id, username или объект канала).
        :return: True, если пользователь состоит в канале, иначе False.
        """
        try:
            client = await self.get_client()
            me = await client.get_me()
            # Запрашиваем информацию об участнике
            participant = await client(GetParticipantRequest(channel=channel, participant=me))
            return True
        except UserNotParticipantError:
            # Если пользователь не найден в списке участников
            return False
        except Exception as e:
            # Обработка прочих возможных исключений
            logger.error(f"Ошибка при проверке участника: {e}")
            return False

    @flood_wait_handler
    async def schedule_reaction(self, reaction: ScheduleReaction):
        try:
            """Ожидает и отправляет реакцию"""
            # Спим
            await asyncio.sleep(reaction.delay)
            # Отправляем
            client = await self.get_client()

            # Превращаем то, что пришло из конфига, в объект Reaction*
            if isinstance(reaction.reaction, int):
                # считаем, что int = document_id премиум-эмодзи
                emotions = [types.ReactionCustomEmoji(document_id=reaction.reaction)]
            else:
                # обычный Unicode-эмодзи
                emotions = [types.ReactionEmoji(emoticon=reaction.reaction)]

            await client(SendReactionRequest(
                peer=reaction.channel_id,
                msg_id=reaction.post_id,
                reaction=emotions
            ))
            logger.info(f"Сессия {self.session_name} поставила реакцию")
        except:
            logger.info(f"Сессия {self.session_name} не поставила реакцию. Ошибка: {traceback.format_exc()}")
