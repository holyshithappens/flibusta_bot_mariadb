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

BOOK_FORMAT_FB2 = 'fb2'
BOOK_FORMAT_MOBI = 'mobi'
BOOK_FORMAT_EPUB = 'epub'
DEFAULT_BOOK_FORMAT = BOOK_FORMAT_FB2  # По умолчанию формат не установлен

# Интервалы мониторинга загрузки и очистки ресурсов
# MONITORING_INTERVAL=1800 # каждые полчаса мониторим потребление памяти
CLEANUP_INTERVAL=3600 # каждый час очищаем старые сохранённые контексты поисков

# Константы для типов настроек
SETTING_MAX_BOOKS = 'max_books'
SETTING_LANG_SEARCH = 'lang_search'
# SETTING_SORT_ORDER = 'sort_order'
SETTING_SIZE_LIMIT = 'size_limit'
SETTING_BOOK_FORMAT = 'book_format'
SETTING_SEARCH_TYPE = 'search_type'
# Константа для типа настройки рейтинга
SETTING_RATING_FILTER = 'rating_filter'
SETTING_SEARCH_AREA = 'aux_search'
SETTING_SEARCH_AREA_B = 'b' # Поиск по основной информации
SETTING_SEARCH_AREA_BA = 'ba' # Поиск по аннотации книг

# SETTING_SORT_ORDER_ASC = 'asc'
# SETTING_SORT_ORDER_DESC = 'desc'

# Словарь соответствия setting_type -> заголовок
SETTING_TITLES = {
    SETTING_MAX_BOOKS: 'Ограничение вывода',
    SETTING_LANG_SEARCH: 'Язык книг',
    # SETTING_SORT_ORDER: 'Сортировку по дате публикации',
    SETTING_SIZE_LIMIT: 'Ограничение на размер книг',
    SETTING_BOOK_FORMAT: 'Формат скачивания книг',
    SETTING_SEARCH_TYPE: 'Вывод результатов',
    SETTING_RATING_FILTER: 'Фильтр по рейтингу',
    SETTING_SEARCH_AREA: 'Область поиска'
}

SEARCH_TYPE_BOOKS = 'books'
SEARCH_TYPE_SERIES = 'series'
SEARCH_TYPE_AUTHORS = 'authors'

# Рейтинги книг с эмодзи
BOOK_RATINGS = {
    0: ("⚪️", "Без рейтинга (0)"),
    1: ("🔴", "Нечитаемо (1)"),
    2: ("🟠", "Плохо (2)"),
    3: ("🟡", "Неплохо (3)"),
    4: ("🟢", "Хорошо (4)"),
    5: ("🔵", "Отлично (5)")
}

# Словарь опций для настроек
SETTING_OPTIONS = {
    SETTING_MAX_BOOKS: [
        (20, '20'),
        (40, '40')
    ],
    # SETTING_SORT_ORDER: [
    #     (SETTING_SORT_ORDER_ASC, 'по возрастанию'),
    #     (SETTING_SORT_ORDER_DESC, 'по убыванию')
    # ],
    SETTING_SIZE_LIMIT: [
        ('less800', '<800K'),
        ('more800', '>800K'),
        ('', 'Сбросить')
    ],
    SETTING_BOOK_FORMAT: [
        (BOOK_FORMAT_FB2, 'FB2'),
        (BOOK_FORMAT_MOBI, 'MOBI'),
        (BOOK_FORMAT_EPUB, 'EPUB')
    ],
    SETTING_SEARCH_TYPE: [
        (SEARCH_TYPE_BOOKS, 'по книгам'),
        (SEARCH_TYPE_SERIES, 'по сериям'),
        (SEARCH_TYPE_AUTHORS, 'по авторам')
    ],
    SETTING_RATING_FILTER: [
        (key, f"{value[0]} {value[1]}") for key, value in BOOK_RATINGS.items()
    ],
    SETTING_SEARCH_AREA: [
        (SETTING_SEARCH_AREA_B, 'по основным данным'),
        (SETTING_SEARCH_AREA_BA, 'по аннотации книг')
    ]
}


# Путь к файлу с новостями (теперь Python файл)
BOT_NEWS_FILE_PATH = "./data/bot_news.py"

