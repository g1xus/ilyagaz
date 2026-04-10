API_ID=2040
API_HASH="b18441a1ff607e10a989891a5462e627"

# Подключение Telethon: таймаут на connect() и число смен прокси из data/proxy.txt
# Меньше ~15 с — частые ложные таймауты на медленных SOCKS (см. лог «Таймаут N с (host:port)»).
CONNECT_TIMEOUT = 25
CONNECT_PROXY_RETRIES = 1
# Если прокси из proxy.txt не подключился — одна попытка без прокси (VPN на ПК и т.п.). Выключите, если без прокси Telegram недоступен.
CONNECT_FALLBACK_DIRECT = True

# SOCKS5 (PySocks): True — резолв доменов на стороне прокси; False — на вашем ПК (часто убирает «вечные» таймауты).
PROXY_SOCKS5_RDNS = False
# После неудачи с текущим rdns — ещё одна попытка с противоположным значением (без второй строки в proxy.txt).
PROXY_TRY_ALT_RDNS = True


# Реации и их процент
CHANNELS = [
    {
        'channel': 'https://t.me/+Gb_06L3nYmExMmYy', #rr
        'reactions': {
            '🤝': 50,
            '👍': 10,
            '❤️': 10,
            '🔥': 30
        },
        'post_reactions':{
            '🔥': 80
        },
        'time': {
            5: 30,
            10: 50,
            15: 25
        },
        'count': 75
    },
    {
        'channel': 'https://t.me/+Zn16bzS9CO9lY2Ni', #PO
        'reactions': {
            '🔥': 70,
            '👍': 20,
            '❤️': 10,
        },
        'post_reactions':{
            '🔥': 90,
        },
        'time': {
            5: 30,
            10: 50,
            15: 25
        },
        'count': 20
    },
    {
        'channel': 'https://t.me/+GNKgVpwP_WFlMTAy', #тест
        'reactions': {
            '🔥': 70,
            '👍': 20,
            '❤️': 10,
        },
        'post_reactions':{
            '🔥': 90,
        },
        'time': {
            5: 30,
            10: 50,
            15: 25
        },
        'count': 20
    },
]
