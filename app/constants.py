# Пути к базам данных и файлам
PREFIX_FILE_PATH = "./data"
PREFIX_TMP_PATH = "./tmp"  # путь для временных файлов и резервных копий
FLIBUSTA_LOG_PATH = './logs'

#FLIBUSTA_DB_BOOKS_PATH = f"{PREFIX_FILE_PATH}/Flibusta_FB2_local.hlc2"
FLIBUSTA_DB_SETTINGS_PATH = f"{PREFIX_FILE_PATH}/FlibustaSettings.sqlite"
FLIBUSTA_DB_LOGS_PATH = f"{PREFIX_FILE_PATH}/FlibustaLogs.sqlite"

# пути для резервных копий
BACKUP_TMP_PATH = PREFIX_TMP_PATH
BACKUP_DB_FILES = [
    FLIBUSTA_DB_SETTINGS_PATH,
    FLIBUSTA_DB_LOGS_PATH
]
BACKUP_LOG_PATTERN = f"{FLIBUSTA_LOG_PATH}/*log*"

# Максимальное количество книг для поиска, это же значение задано по умолчанию для поля UserSettings.MaxBooks
MAX_BOOKS_SEARCH = 2000

#WEB
FLIBUSTA_BASE_URL = "https://www.flibusta.is"
DEFAULT_BOOK_FORMAT = 'fb2'  # По умолчанию формат не установлен

# Интервалы мониторинга загрузки и очистки ресурсов
# MONITORING_INTERVAL=1800 # каждые полчаса мониторим потребление памяти
CLEANUP_INTERVAL=3600 # каждый час очищаем старые сохранённые контексты поисков

# Константы для типов настроек
SETTING_MAX_BOOKS = 'max_books'
SETTING_LANG_SEARCH = 'lang_search'
SETTING_SORT_ORDER = 'sort_order'
SETTING_SIZE_LIMIT = 'size_limit'
SETTING_BOOK_FORMAT = 'book_format'
SETTING_SEARCH_TYPE = 'search_type'
# Константа для типа настройки рейтинга
SETTING_RATING_FILTER = 'rating_filter'

# Словарь соответствия setting_type -> заголовок
SETTING_TITLES = {
    SETTING_MAX_BOOKS: 'Ограничение вывода',
    SETTING_LANG_SEARCH: 'Язык книг',
    SETTING_SORT_ORDER: 'Порядок сортировки по дате публикации',
    SETTING_SIZE_LIMIT: 'Ограничение на размер книг',
    SETTING_BOOK_FORMAT: 'Формат скачивания книг',
    SETTING_SEARCH_TYPE: 'Вывод результатов',
    SETTING_RATING_FILTER: 'Фильтр по рейтингу'
}

# Словарь опций для настроек
SETTING_OPTIONS = {
    SETTING_MAX_BOOKS: [
        (20, '20'),
        (40, '40')
    ],
    SETTING_SORT_ORDER: [
        ('asc', 'По возрастанию'),
        ('desc', 'По убыванию')
    ],
    SETTING_SIZE_LIMIT: [
        ('less800', '<800K'),
        ('more800', '>800K'),
        ('', 'Сбросить')
    ],
    SETTING_BOOK_FORMAT: [
        ('fb2', 'FB2'),
        ('mobi', 'MOBI'),
        ('epub', 'EPUB')
    ],
    SETTING_SEARCH_TYPE: [
        ('books', 'По книгам'),
        ('series', 'По сериям'),
        ('authors', 'По авторам')
    ],
    SETTING_RATING_FILTER: [
        (0, '⚪️ Без рейтинга (0)'),
        (1, '🔴 Нечитаемо (1)'),
        (2, '🟠 Плохо (2)'),
        (3, '🟡 Неплохо (3)'),
        (4, '🟢 Хорошо (4)'),
        (5, '🔵 Отлично (5)')
    ]
}

# Рейтинги книг с эмодзи
BOOK_RATINGS = {
    0: ("⚪️", "Без рейтинга (0)"),
    1: ("🔴", "Нечитаемо (1)"),
    2: ("🟠", "Плохо (2)"),
    3: ("🟡", "Неплохо (3)"),
    4: ("🟢", "Хорошо (4)"),
    5: ("🔵", "Отлично (5)")
}

# Путь к файлу с новостями (теперь Python файл)
BOT_NEWS_FILE_PATH = "./data/bot_news.py"

