# Константы для ключей контекста
from datetime import datetime


class CMConst:
    class CMC_UserParams:
        USER_PARAMS = 'USER_PARAMS'

    class CMC_Proc:
        LAST_ACTIVITY = 'last_activity'
        LAST_SERIES_PAGE = 'last_series_page'
        LAST_AUTHORS_PAGE = 'last_authors_page'
        CURRENT_AUTHOR_ID = 'author_id'
        CURRENT_SERIES_NAME = 'current_series_name'
        CURRENT_AUTHOR_NAME = 'current_author_name'
        LAST_BOT_MESSAGE_ID = 'last_bot_message_id'
        LAST_SEARCH_QUERY = 'last_search_query'
        # LAST_BOOK_INFO_MESSAGE_ID = 'last_book_info_message_id'  # ключ не используется

    # Ключи для поисковых данных
    class CMC_SearchData:
        BOOKS = 'BOOKS'
        PAGES_OF_BOOKS = 'PAGES_OF_BOOKS'
        FOUND_BOOKS_COUNT = 'FOUND_BOOKS_COUNT'
        SERIES = 'SERIES'
        PAGES_OF_SERIES = 'PAGES_OF_SERIES'
        FOUND_SERIES_COUNT = 'FOUND_SERIES_COUNT'
        AUTHORS = 'AUTHORS'
        PAGES_OF_AUTHORS = 'PAGES_OF_AUTHORS'
        FOUND_AUTHORS_COUNT = 'FOUND_AUTHORS_COUNT'


class ContextManager:
    _instance = None
    _db_settings = None

    @classmethod
    def _init_db(cls):
        """Ленивая инициализация БД"""
        if cls._db_settings is None:
            from database import DatabaseSettings
            cls._db_settings = DatabaseSettings()

    @classmethod
    def _get_ids_from_context(cls, context):
        """Извлекает user_id и chat_id из контекста"""
        user_id = getattr(context, '_user_id', None)
        chat_id = getattr(context, '_chat_id', None)
        return user_id, chat_id

    @classmethod
    def _get_bot_context_key(cls, context):
        """Формирует ключ данных в контексте бота по char_id"""
        user_id, chat_id = cls._get_ids_from_context(context)
        return f"group_search_{chat_id}"

    @classmethod
    def _get_context_data(cls, context):
        """Получает соответствующий словарь контекста с автоматическим определением типа чата"""
        user_id, chat_id = cls._get_ids_from_context(context)
        is_private_chat = (user_id == chat_id)

        if is_private_chat:
            return context.user_data if hasattr(context, 'user_data') else {}
        else:
            if chat_id and hasattr(context, 'bot_data'):
                search_context_key = cls._get_bot_context_key(context)
                if search_context_key not in context.bot_data:
                    context.bot_data[search_context_key] = {}
                return context.bot_data[search_context_key]
            return {}

    @classmethod
    def get(cls, context, key, default=None):
        """Универсальный геттер для контекста"""
        # Особый случай для USER_PARAMS - загружаем из БД при необходимости
        if key == CMConst.CMC_UserParams.USER_PARAMS:
            return cls._get_user_params(context)

        data = cls._get_context_data(context)
        return data.get(key, default)

    @classmethod
    def set(cls, context, key, value):
        """Универсальный сеттер для контекста"""
        # Особый случай для USER_PARAMS - обновляем в БД
        if key == CMConst.CMC_UserParams.USER_PARAMS:
            cls._update_user_params(context, value)
            return

        data = cls._get_context_data(context)
        data[key] = value

    @classmethod
    def delete(cls, context, key):
        """Удаляет ключ из контекста"""
        data = cls._get_context_data(context)
        if key in data:
            del data[key]

    @classmethod
    def clear_search_data(cls, context):
        """Очищает все поисковые данные"""
        search_keys = [value for key, value in vars(CMConst.CMC_SearchData).items()
                       if not key.startswith('_')]

        data = cls._get_context_data(context)
        for key in search_keys:
            if key in data:
                del data[key]

    @classmethod
    def _get_user_params(cls, context):
        """Получает настройки пользователя из контекста или БД"""
        cls._init_db()
        user_id, chat_id = cls._get_ids_from_context(context)

        if not user_id:
            return None

        # Пытаемся получить из контекста
        data = cls._get_context_data(context)
        if CMConst.CMC_UserParams.USER_PARAMS in data:
            return data[CMConst.CMC_UserParams.USER_PARAMS]

        # Загружаем из БД
        user_settings = cls._db_settings.get_user_settings(user_id)

        # Сохраняем в контекст
        data[CMConst.CMC_UserParams.USER_PARAMS] = user_settings

        return user_settings

    @classmethod
    def _update_user_params(cls, context, user_params):
        """Обновляет настройки пользователя в БД и контексте"""
        cls._init_db()
        user_id, chat_id = cls._get_ids_from_context(context)

        if not user_id:
            return

        # Обновляем в БД
        update_dict = user_params._asdict() if hasattr(user_params, '_asdict') else user_params
        cls._db_settings.update_user_settings(user_id, **update_dict)

        # Обновляем в контексте
        data = cls._get_context_data(context)
        data[CMConst.CMC_UserParams.USER_PARAMS] = user_params

    @classmethod
    def update_user_params_partial(cls, context, **kwargs):
        """Частичное обновление настроек пользователя"""
        cls._init_db()
        user_id, chat_id = cls._get_ids_from_context(context)

        if not user_id:
            return

        # Получаем текущие настройки
        current_params = cls._get_user_params(context)
        if not current_params:
            return

        # Обновляем в БД
        cls._db_settings.update_user_settings(user_id, **kwargs)

        # Обновляем в контексте
        if hasattr(current_params, '_asdict'):
            current_dict = current_params._asdict()
            current_dict.update(kwargs)
            data = cls._get_context_data(context)
            data[CMConst.CMC_UserParams.USER_PARAMS] = cls._db_settings.UserSettingsType(**current_dict)

    @classmethod
    def cleanup_inactive_sessions(cls, app, cleanup_interval):
        """Очищает неактивные сессии"""
        cleaned_count_private = 0
        cleaned_count_group = 0

        # Очистка личных чатов
        if hasattr(app, 'user_data'):
            for user_id, user_data in app.user_data.items():
                if cls._should_cleanup_session(user_data, cleanup_interval):
                    cls._cleanup_user_session(user_data)
                    cleaned_count_private += 1

        # Очистка групповых чатов
        if hasattr(app, 'bot_data'):
            for key in list(app.bot_data.keys()):
                if key.startswith('group_search_'):
                    bot_data = app.bot_data[key]
                    if cls._should_cleanup_session(bot_data, cleanup_interval):
                        del app.bot_data[key]
                        cleaned_count_group += 1

        return cleaned_count_private, cleaned_count_group

    @classmethod
    def _should_cleanup_session(cls, session_data, cleanup_interval):
        """Проверяет, нужно ли очищать сессию"""
        if not isinstance(session_data, dict):
            return False

        last_activity = session_data.get(CMConst.CMC_Proc.LAST_ACTIVITY)
        return (isinstance(last_activity, datetime) and
                (datetime.now() - last_activity).total_seconds() > cleanup_interval)

    @classmethod
    def _cleanup_user_session(cls, user_data):
        """Очищает данные пользовательской сессии"""
        for key in[value for key, value in vars(CMConst.CMC_Proc).items() if not key.startswith('_')]:
            if key in user_data:
                del user_data[key]


# Специализированные геттеры для часто используемых ключей
def set_last_activity(context, dt):
    ContextManager.set(context, CMConst.CMC_Proc.LAST_ACTIVITY, dt)

def get_last_series_page(context):
    return ContextManager.get(context, CMConst.CMC_Proc.LAST_SERIES_PAGE)

def set_last_series_page(context, page):
    ContextManager.set(context, CMConst.CMC_Proc.LAST_SERIES_PAGE, page)

def get_last_authors_page(context):
    return ContextManager.get(context, CMConst.CMC_Proc.LAST_AUTHORS_PAGE)

def set_last_authors_page(context, page):
    ContextManager.set(context, CMConst.CMC_Proc.LAST_AUTHORS_PAGE, page)

def get_current_series_name(context):
    return ContextManager.get(context, CMConst.CMC_Proc.CURRENT_SERIES_NAME)

def set_current_series_name(context, series):
    ContextManager.set(context, CMConst.CMC_Proc.CURRENT_SERIES_NAME, series)

def get_current_author_id(context):
    return ContextManager.get(context, CMConst.CMC_Proc.CURRENT_AUTHOR_ID)

def set_current_author_id(context, author_id):
    ContextManager.set(context, CMConst.CMC_Proc.CURRENT_AUTHOR_ID, author_id)

def get_current_author_name(context):
    return ContextManager.get(context, CMConst.CMC_Proc.CURRENT_AUTHOR_NAME)

def set_current_author_name(context, author_name):
    ContextManager.set(context, CMConst.CMC_Proc.CURRENT_AUTHOR_NAME, author_name)

def get_last_bot_message_id(context):
    return ContextManager.get(context, CMConst.CMC_Proc.LAST_BOT_MESSAGE_ID)

def set_last_bot_message_id(context, message_id):
    ContextManager.set(context, CMConst.CMC_Proc.LAST_BOT_MESSAGE_ID, message_id)

def get_last_search_query(context):
    return ContextManager.get(context, CMConst.CMC_Proc.LAST_SEARCH_QUERY)

def set_last_search_query(context, query):
    ContextManager.set(context, CMConst.CMC_Proc.LAST_SEARCH_QUERY, query)

# Данные поиска
def get_pages_of_books(context):
    return ContextManager.get(context, CMConst.CMC_SearchData.PAGES_OF_BOOKS)

def get_pages_of_series(context):
    return ContextManager.get(context, CMConst.CMC_SearchData.PAGES_OF_SERIES)

def get_pages_of_authors(context):
    return ContextManager.get(context, CMConst.CMC_SearchData.PAGES_OF_AUTHORS)

def get_found_books_count(context):
    return ContextManager.get(context, CMConst.CMC_SearchData.FOUND_BOOKS_COUNT)

def get_found_series_count(context):
    return ContextManager.get(context, CMConst.CMC_SearchData.FOUND_SERIES_COUNT)

def get_found_authors_count(context):
    return ContextManager.get(context, CMConst.CMC_SearchData.FOUND_AUTHORS_COUNT)

def set_books(context, books, pages, count):
    ContextManager.set(context, CMConst.CMC_SearchData.BOOKS, books)
    ContextManager.set(context, CMConst.CMC_SearchData.PAGES_OF_BOOKS, pages)
    ContextManager.set(context, CMConst.CMC_SearchData.FOUND_BOOKS_COUNT, count)

def set_series(context, series, pages, count):
    ContextManager.set(context, CMConst.CMC_SearchData.SERIES, series)
    ContextManager.set(context, CMConst.CMC_SearchData.PAGES_OF_SERIES, pages)
    ContextManager.set(context, CMConst.CMC_SearchData.FOUND_SERIES_COUNT, count)

def set_authors(context,authors, pages, count):
    ContextManager.set(context, CMConst.CMC_SearchData.AUTHORS, authors)
    ContextManager.set(context, CMConst.CMC_SearchData.PAGES_OF_AUTHORS, pages)
    ContextManager.set(context, CMConst.CMC_SearchData.FOUND_AUTHORS_COUNT, count)



# Специальные функции для USER_PARAMS
def get_user_params(context):
    """Получает настройки пользователя (с загрузкой из БД при необходимости)"""
    return ContextManager.get(context, CMConst.CMC_UserParams.USER_PARAMS)


def update_user_params(context, **kwargs):
    """Обновляет настройки пользователя в БД и контексте"""
    ContextManager.update_user_params_partial(context, **kwargs)