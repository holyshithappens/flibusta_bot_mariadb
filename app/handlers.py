from datetime import datetime
import os
from typing import List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, LabeledPrice
from telegram.constants import ParseMode
from telegram.error import TimedOut, BadRequest, Forbidden
from telegram.ext import CallbackContext, ContextTypes

from database import DatabaseBooks, DatabaseSettings
from constants import FLIBUSTA_BASE_URL, DEFAULT_BOOK_FORMAT, \
    SETTING_MAX_BOOKS, SETTING_LANG_SEARCH, SETTING_SORT_ORDER, SETTING_SIZE_LIMIT, \
    SETTING_BOOK_FORMAT, SETTING_SEARCH_TYPE, SETTING_OPTIONS, SETTING_TITLES, SETTING_RATING_FILTER, BOOK_RATINGS, \
    BOT_NEWS_FILE_PATH, SETTING_SEARCH_AREA, SETTING_SEARCH_AREA_B, SETTING_SEARCH_AREA_BA, SEARCH_TYPE_BOOKS, \
    SEARCH_TYPE_SERIES, SEARCH_TYPE_AUTHORS
from health import log_stats
from utils import format_size, get_platform_recommendations, download_book_with_filename, upload_to_tmpfiles, \
    is_message_for_bot, extract_clean_query, get_latest_news, format_book_reviews, format_author_info, \
    format_book_details, format_book_info, form_header_books
from logger import logger

# ===== КОНСТАНТЫ И КОНФИГУРАЦИЯ =====
DB_BOOKS = DatabaseBooks({
    'host': os.getenv('DB_HOST'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'charset': os.getenv('DB_CHARSET', 'utf8mb4')
})
DB_SETTINGS = DatabaseSettings()

USER_PARAMS = 'USER_PARAMS'

BOOKS = 'BOOKS'
PAGES_OF_BOOKS = 'PAGES_OF_BOOKS'
FOUND_BOOKS_COUNT = 'FOUND_BOOKS_COUNT'

# SEARCH_CONTEXT = 'SEARCH_CONTEXT'

SERIES = 'SERIES'
PAGES_OF_SERIES = 'PAGES_OF_SERIES'
FOUND_SERIES_COUNT = 'FOUND_SERIES_COUNT'

AUTHORS = 'AUTHORS'
PAGES_OF_AUTHORS = 'PAGES_OF_AUTHORS'
FOUND_AUTHORS_COUNT = 'FOUND_AUTHORS_COUNT'

CONTACT_INFO = {'email': os.getenv("FEEDBACK_EMAIL", "не указан"), 'pikabu': os.getenv("FEEDBACK_PIKABU", ""),
                'pikabu_username': os.getenv("FEEDBACK_PIKABU_USERNAME", "не указан")}


# ===== УТИЛИТЫ И ХЕЛПЕРЫ =====
def create_back_button() -> list:
    """Создает кнопку возврата в настройки"""
    return [[InlineKeyboardButton("⬅ Назад в настройки", callback_data="back_to_settings")]]


def add_close_button(keyboard):
    """Добавляем к клавиатуре кнопку закрытия"""
    return keyboard.append([InlineKeyboardButton("❌ Закрыть", callback_data="close_message")])


def get_rating_emoji(rating):
    """Возвращает эмодзи для рейтинга"""
    return BOOK_RATINGS.get(rating, ("⚪️", ""))[0]


async def edit_or_reply_message(query, text, reply_markup=None):
    """Редактирует существующее сообщение или отправляет новое"""
    if hasattr(query.message, 'message_id'):
        await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await query.message.reply_text(text, reply_markup=reply_markup)


async def process_book_download(query, book_id, book_format, file_name, for_user=None):
    """Обрабатывает скачивание и отправку книги"""
    processing_msg = await query.message.reply_text(
        "⏰ <i>Ожидайте, отправляю книгу"+(f" для {for_user.first_name}" if for_user else "")+"...</i>",
        parse_mode=ParseMode.HTML,
        disable_notification=True
    )

    try:
        url = f"{FLIBUSTA_BASE_URL}/b/{book_id}/{book_format}"
        book_data, original_filename = await download_book_with_filename(url)
        public_filename = original_filename if original_filename else f"{book_id}.{book_format}"

        if book_data:
            await query.message.reply_document(
                document=book_data,
                filename=public_filename,
                disable_notification=True
            )
        else:
            await query.message.reply_text(
                "😞 Не удалось скачать книгу в этом формате" + (f" для {for_user.first_name}" if for_user else "") +
                f" ({url})",
                disable_notification=True
            )

        await processing_msg.delete()
        return public_filename

    except TimedOut:
        await handle_timeout_error(processing_msg, book_data, file_name, book_format, query)
    except Exception as e:
        """Обрабатывает ошибку загрузки"""
        print(f"Общая ошибка при отправке книги: {e}")
        await processing_msg.edit_text(
            f"❌ Произошла ошибка при подготовке книги {url}. Возможно она доступна только в локальной базе"
        )
        logger.log_user_action(query.from_user.id, "error sending book direct", url)

    return None


async def handle_timeout_error(processing_msg, book_data, file_name, file_ext, query):
    """Обрабатывает ошибку таймаута"""
    await processing_msg.edit_text(
        "⏳ Книга большая, использую внешний сервис...",
        parse_mode=ParseMode.HTML
    )

    try:
        download_url = await upload_to_tmpfiles(book_data, f"{file_name}.{file_ext}")
        if download_url:
            direct_download_url = download_url.replace(
                "https://tmpfiles.org/",
                "https://tmpfiles.org/dl/",
                1
            )
            message = (
                f"<a href='{direct_download_url}'>📥 Скачать книгу</a>\n"
                "⏳ Ссылка действительна 15 минут"
            )
            await query.message.reply_text(
                text=message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                disable_notification=True
            )
    except Exception as upload_error:
        print(f"Ошибка загрузки на tmpfiles: {upload_error}")
        await processing_msg.edit_text("❌ Не удалось отправить книгу. Попробуйте позже.")
        logger.log_user_action(query.from_user.id, "error sending book cloud", f"{file_name}{file_ext}")


# ===== КЛАВИАТУРЫ И ИНТЕРФЕЙС =====
def create_books_keyboard(page, pages_of_books, search_context=SEARCH_TYPE_BOOKS):
    # reply_markup = None
    keyboard = []

    if pages_of_books:
        books_in_page = pages_of_books[page]

        if books_in_page:
            for book in books_in_page:
                # ДОБАВЛЯЕМ ЭМОДЗИ РЕЙТИНГА
                rating_emoji = get_rating_emoji(book.LibRate)
                text = f"{rating_emoji} {book.Title} ({book.LastName} {book.FirstName}) {format_size(book.BookSize)}/{book.Genre}"
                if book.SearchYear != 0:
                    text += f"/{str(book.SearchYear)}"
                keyboard.append([InlineKeyboardButton(
                    text,
                    callback_data = f"book_info:{book.FileName}"
                )])

            # Добавляем кнопки для навигации
            navigation_buttons = []
            if page > 0:
                navigation_buttons.append(InlineKeyboardButton("⬆ В начало", callback_data=f"page_0"))
                navigation_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"page_{page - 1}"))
            if page < len(pages_of_books) - 1:
                navigation_buttons.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f"page_{page + 1}"))
                navigation_buttons.append(InlineKeyboardButton("В конец ⬇️️️", callback_data=f"page_{len(pages_of_books) - 1}"))
            if navigation_buttons:
                keyboard.append(navigation_buttons)

            # Добавляем кнопку "Назад к сериям" только при поиске по сериям
            if search_context == SEARCH_TYPE_SERIES:
                keyboard.append([InlineKeyboardButton("⤴️ Назад к сериям", callback_data="back_to_series")])

            # Добавляем кнопку "Назад к авторам" при поиске по авторам
            elif search_context == SEARCH_TYPE_AUTHORS:
                keyboard.append([InlineKeyboardButton("⤴️ Назад к авторам", callback_data="back_to_authors")])

    return keyboard


def create_series_keyboard(page, pages_of_series):
    """ Создание клавиатуры с кнопками из найденных серий книг """
    keyboard = []

    if pages_of_series:
        series_in_page = pages_of_series[page]

        if series_in_page:
            for idx, (series_name, series_id, book_count) in enumerate(series_in_page):
                text = f"{series_name} ({book_count})"
                keyboard.append([InlineKeyboardButton(
                    text,
                    callback_data = f"show_series:{series_id}"
                )])

            # Добавляем кнопки для навигации
            navigation_buttons = []
            if page > 0:
                navigation_buttons.append(InlineKeyboardButton("⬆ В начало", callback_data=f"series_page_0"))
                navigation_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"series_page_{page - 1}"))
            if page < len(pages_of_series) - 1:
                navigation_buttons.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f"series_page_{page + 1}"))
                navigation_buttons.append(
                    InlineKeyboardButton("В конец ⬇️️️", callback_data=f"series_page_{len(pages_of_series) - 1}"))
            if navigation_buttons:
                keyboard.append(navigation_buttons)

    return keyboard


def create_authors_keyboard(page, pages_of_authors):
    """ создание клавиатуры для авторов """
    keyboard = []

    if pages_of_authors:
        authors_in_page = pages_of_authors[page]

        if authors_in_page:
            for idx, (author_name, book_count, author_id) in enumerate(authors_in_page):
                text = f"{author_name} ({book_count})"
                keyboard.append([InlineKeyboardButton(
                    text,
                    callback_data = f"show_author:{author_id}"
                )])

            # Добавляем кнопки для навигации
            navigation_buttons = []
            if page > 0:
                navigation_buttons.append(InlineKeyboardButton("⬆ В начало", callback_data=f"authors_page_0"))
                navigation_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"authors_page_{page - 1}"))
            if page < len(pages_of_authors) - 1:
                navigation_buttons.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f"authors_page_{page + 1}"))
                navigation_buttons.append(
                    InlineKeyboardButton("В конец ⬇️️️", callback_data=f"authors_page_{len(pages_of_authors) - 1}"))
            if navigation_buttons:
                keyboard.append(navigation_buttons)

    return keyboard


def create_settings_menu():
    """Создает главное меню настроек"""
    settings = [(text, setting_type) for setting_type, text in SETTING_TITLES.items()]

    keyboard = [[InlineKeyboardButton(text, callback_data=f"set_{key}")] for text, key in settings]
    return keyboard


def create_settings_keyboard(setting_type, current_value, options):
    """
    Создает клавиатуру для настроек с галочками и кнопкой назад
    :param setting_type: тип настройки (для callback_data)
    :param current_value: текущее значение настройки
    :param options: список опций в формате [(value, display_text), ...]
    """
    keyboard = []

    if setting_type == SETTING_LANG_SEARCH:
        # Особый случай для языка - добавляем кнопку сброса
        if current_value:
            keyboard.append([
                InlineKeyboardButton(
                    f"✔ {current_value} - сбросить",
                    callback_data=f"set_{setting_type}_to_"
                )
            ])

        # Создаем кнопки языков
        buttons = []
        for value, display_text in options:
            buttons.append(InlineKeyboardButton(
                f"{display_text}",
                callback_data=f"set_{setting_type}_to_{value}"
            ))

        # Группируем по 8 кнопок в строку
        keyboard.extend([buttons[i:i + 8] for i in range(0, len(buttons), 8)])

    else:
        # Для остальных настроек - кнопки в строку
        row = []
        for value, display_text in options:
            row.append(InlineKeyboardButton(
                f"{'✔️ ' if str(value) == str(current_value) else ''}{display_text}",
                callback_data=f"set_{setting_type}_to_{value}"
            ))
        keyboard.append(row)

    # Добавляем кнопку "Назад"
    keyboard += create_back_button()

    return InlineKeyboardMarkup(keyboard)


def create_rating_filter_keyboard(current_ratings, options):
    """Создает клавиатуру для множественного выбора рейтингов"""
    keyboard = []

    for value, display_text in options:
        is_selected = str(value) in current_ratings
        emoji = "✔" if is_selected else ""
        button_text = f"{emoji} {display_text}"

        keyboard.append([InlineKeyboardButton(
            button_text,
            callback_data=f"toggle_rating_{value}"
        )])

    # Кнопка сброса
    keyboard.append([InlineKeyboardButton("🔄 Сбросить все", callback_data="reset_ratings")])

    # Кнопка назад
    keyboard += create_back_button()

    return InlineKeyboardMarkup(keyboard)


# ===== КОМАНДЫ БОТА =====
async def start_cmd(update: Update, context: CallbackContext):
    """Обработка команды /start с deep linking"""
    user = update.effective_user

    # # Сохраняем настройки пользователя
    # user_params = DB_SETTINGS.get_user_settings(user.id)
    # context.user_data[USER_PARAMS] = user_params

    #Вывод приглашения и помощи по поиску книг
    welcome_text = """
📚 <b>Привет! Я помогу тебе искать и скачивать книги непосредственно из библиотеки Флибуста.</b> 

<u>Управление</u>
/news - новости и обновления бота
/about - информация о боте и библиотеке 
/help - помощь в составлении поисковых запросов
/genres - посмотреть доступные жанры
/langs - посмотреть доступные языки книг по убыванию их количества
/set - установка настроек поиска и вывода книг
/donate - поддержать разработчика
    """
    await update.message.reply_text(welcome_text, parse_mode='HTML', disable_web_page_preview=True)

    # # user = update.message.from_user
    # user_params = DB_SETTINGS.get_user_settings(user.id)
    # context.user_data[USER_PARAMS] = user_params

    await log_stats(context)

    logger.log_user_action(user, "started bot")


async def genres_cmd(update: Update, context: CallbackContext):
    """Показывает родительские жанры"""
    try:
        results = DB_BOOKS.get_parent_genres_with_counts()

        # print(f"DEBUG: genres_cmd results = {results}")
        # print(f"DEBUG: Number of results = {len(results)}")

        keyboard = []
        for genre, count in results:
        # for i, (genre, count) in enumerate(results):
            count_text = f"({count:,})".replace(","," ") if count else "(0)"
            button_text = f"{genre} {count_text}"
            # print(f"DEBUG: Button {i}: '{button_text}' -> callback: 'show_genres:{genre}'")
            genre_index = results.index((genre, count))
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"show_genres:{genre_index}")])

        # print(f"DEBUG: Keyboard has {len(keyboard)} rows")

        reply_markup = InlineKeyboardMarkup(keyboard)
        # print(f"DEBUG: Reply markup created")

        await update.message.reply_text("Посмотреть жанры:", reply_markup=reply_markup)
        # print(f"DEBUG: Message sent successfully")
    except Exception as e:
        # print(f"Error in genres_cmd: {e}")
        await update.message.reply_text("❌ Ошибка при загрузке жанров")

    await log_stats(context)
    user = update.message.from_user
    logger.log_user_action(user, "viewed parent genres")


async def langs_cmd(update: Update, context: CallbackContext):
    """Показывает доступные языки"""
    results = DB_BOOKS.get_langs()
    langs = ", ".join([f"<code>{lang[0].strip()}</code>" for lang in results])
    await update.message.reply_text(
        langs,
        parse_mode=ParseMode.HTML,
        disable_notification=True
    )

    await log_stats(context)
    user = update.message.from_user
    logger.log_user_action(user, "viewed langs of books")


async def settings_cmd(update: Update, context: CallbackContext):
    """Показывает главное меню настроек"""
    await show_settings_menu(update, context, from_callback=False)


async def donate_cmd(update: Update, context: CallbackContext):
    """Команда /donate с HTML сообщением"""
    addresses = {
        '₿ Bitcoin (BTC)': os.getenv('DONATE_BTC'),
        'Ξ Ethereum & Poligon (ETH & POL)': os.getenv('DONATE_ETH'),
        '◎ Solana (SOL & USDC)': os.getenv('DONATE_SOL'),
        '🔵 Sui (SUI)': os.getenv('DONATE_SUI'),
        '₮ Toncoin (TON & USDT)': os.getenv('DONATE_TON'),
        '🔴 Tron (TRX & USDT)': os.getenv('DONATE_TRX')
    }

    donate_html = "💰 <b>Поддержать разработчика крипто-копеечкой</b>"
    for crypto_name, address in addresses.items():
        if address:
            donate_html += f"\n{crypto_name}:\n<code>{address}</code>\n"

    await update.message.reply_text(
        donate_html,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

    user = update.message.from_user
    logger.log_user_action(user, "viewed donate page")

    try:
        chat_id = update.message.chat_id
        title = "Поддержать разработчика"
        payload = "donation-payload"
        currency = "XTR"  # Telegram Stars

        descr_5 = "Так, просто так!"
        prices_5 = [LabeledPrice("5 звёзд", 5),]
        await send_invoice(context, chat_id, title, descr_5, payload, currency, prices_5)
        descr_50 = "Примерно неделя аренды текущего VPS"
        prices_50 = [LabeledPrice("50 звезда", 50),]
        await send_invoice(context, chat_id, title, descr_50, payload, currency, prices_50)
        descr_200 = "Примерно месяц аренды текущего VPS"
        prices_200 = [LabeledPrice("200 звёзд", 200),]
        await send_invoice(context, chat_id, title, descr_200, payload, currency, prices_200)
        descr_1200 = "Примерно полгода аренды текущего VPS"
        prices_1200 = [LabeledPrice("1200 звёзд", 1200),]
        await send_invoice(context, chat_id, title, descr_1200, payload, currency, prices_1200)

    except Exception as e:
        print(f"Ошибка при создании инвойса: {e}")
        await update.message.reply_text("Произошла ошибка при создании платежа")


async def help_cmd(update: Update, context: CallbackContext):
    """Команда помощи со списком всех команд"""
    help_text = """
    <b>Помощь в поиске книг.</b>

    <u>Простой поиск по любым словам:</u>
    ✏️ <code>Лев Толстой Война и мир</code>
    ✏️ <code>фантастика звёзды 2025</code>
    ✏️ <code>harry potter</code>
    ✏️ <code>Перельман математика</code>

    <u>Советы для эффективного поиска:</u>
    🔍 <b>Несколько слов</b> - бот ищет книги, содержащие какие-либо из перечисленных слов
    🔍 <b>Обязательное слово</b> - используйте + перед словом: <code>+жизнь +замечательных людей</code>
    🔍 <b>Исключение слов</b> - используйте - перед словом: <code>+Распутин -Валентин</code>
    🔍 <b>Части слов</b> - можно использовать *: <code>математич*</code>
    🔍 <b>Группировка слов</b> - используйте (): <code>+(эльф гоблин орк гном) +(одинокий злой грустный огромный)</code>
    🔍 <b>Поиск по аннотациям</b> - в настройках включите "Область поиска" → "По аннотации книг"

    <u>Область поиска:</u>
    📖 Основной поиск осуществляется по: <b>названию книги, авторам, жанрам, серии и году издания</b>
    📝 Поиск по аннотациям - по <b>полным текстам описаний книг</b>. Выполнена индексация слов от трёх букв

    <u>Ограничение выдачи:</u>
    📊 Результаты поиска ограничены <b>2000 строками</b> для скорости работы

    <u>Доступные форматы выдачи (в настройках):</u>
    📚 <b>По книгам</b> - список книг
    👥 <b>По авторам</b> - группировка по авторам
    📖 <b>По сериям</b> - группировка по сериям

    💡 <i>Поиск стал значительно быстрее благодаря полнотекстовой индексации!</i>
    """

    await update.message.reply_text(help_text, parse_mode='HTML', disable_web_page_preview=True)

    user = update.message.from_user
    logger.log_user_action(user, "showed help")


async def about_cmd(update: Update, context: CallbackContext):
    """Команда /about - информация о боте и библиотеке"""
    try:
        stats = DB_BOOKS.get_library_stats()
        last_update = stats['last_update']
        last_update_str = last_update

        # print(f"DEBUG: {last_update}, {last_update_str}")

        reader_recommendations = get_platform_recommendations()

        about_text = f"""
<b>Flibusta Bot</b> - телеграм бот для поиска и скачивания книг непосредственно с сайта библиотеки Флибуста.

📊 <b>Статистика БД библиотеки бота:</b>
• 📚 Книг: <code>{f"{stats['books_count']:,}".replace(",", " ")}</code>
• 👥 Авторов: <code>{f"{stats['authors_count']:,}".replace(",", " ")}</code>
• 📖 Серий: <code>{f"{stats['series_count']:,}".replace(",", " ")}</code>
• 🏷️ Жанров: <code>{stats['genres_count']}</code>
• 🌐 Языков: <code>{stats['languages_count']}</code>
• 📅 Обновлено: <code>{last_update_str}</code>
• 🔢 Максимальный ID файла книги: <code>{stats['max_filename']}</code>

⚡ <b>Возможности бота:</b>
• 🔍 Поиск книг по названию, автору, жанру, серии, языку и году
• 📝 <b>Поиск по аннотациям</b> - полнотекстовый поиск по описаниям книг
• 📚 Поиск с группировкой по сериям и авторам
• 👤 Детальная информация об авторах с фото и биографией
• 📖 Аннотации к книгам и отзывы читателей
• 🖼️ Обложки книг и фото авторов с сайта Флибуста
• 📥 Скачивание в форматах fb2, epub, mobi
• ⭐ Фильтрация по рейтингу книг
• ⚙️ Гибкие настройки поиска
{reader_recommendations}
📞 <b>Обратная связь:</b>
• 📧 Email: <code>{CONTACT_INFO['email']}</code>
• 🎮 Пикабу: <a href="{CONTACT_INFO['pikabu']}">{CONTACT_INFO['pikabu_username']}</a>
• 📢 ТГ-канал: https://t.me/FlibustaBotNews

🛠 <b>Технологии:</b>
• Python 3.11 + python-telegram-bot
• MariaDB + родная БД Флибусты
        """

        await update.message.reply_text(
            about_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    except Exception as e:
        print(f"Error in about command: {e}")
        await update.message.reply_text(
            "❌ Не удалось получить информацию о библиотеке",
            parse_mode=ParseMode.HTML
        )

    await log_stats(context)

    user = update.message.from_user
    logger.log_user_action(user, "viewed about")


async def news_cmd(update: Update, context: CallbackContext):
    """Команда /news - показывает последние новости бота"""
    try:
        # Загружаем новости из файла
        latest_news = await get_latest_news(BOT_NEWS_FILE_PATH, count=3)

        if not latest_news:
            await update.message.reply_text(
                "📢 Пока нет новостей. Следите за обновлениями!",
                parse_mode=ParseMode.HTML
            )
            return

        news_text = "📢 <b>Последние новости бота:</b>\n\n"

        for i, news_item in enumerate(latest_news, 1):
            news_text += f"📅 <b>{news_item['date']}</b>\n"
            news_text += f"<b>{news_item['title']}</b>\n"
            news_text += f"{news_item['content']}\n"

            # Добавляем разделитель между новостями (кроме последней)
            if i < len(latest_news):
                news_text += "─" * 18 + "\n\n"

        await update.message.reply_text(
            news_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

        # Логируем действие
        user = update.message.from_user
        logger.log_user_action(user, "viewed news")

    except Exception as e:
        print(f"Error in news command: {e}")
        await update.message.reply_text(
            "❌ Не удалось загрузить новости",
            parse_mode=ParseMode.HTML
        )


# ===== ПОИСК И НАВИГАЦИЯ =====
async def handle_message(update: Update, context: CallbackContext):
    """Обрабатывает текстовые сообщения (поиск книг или серий)"""
    try:
        # Обрабатываем новый запрос
        # search_type = context.user_data.get(SETTING_SEARCH_TYPE, 'books')
        user = update.effective_message.from_user
        user_params = DB_SETTINGS.get_user_settings(user.id)
        search_type = user_params.SearchType

        if search_type == SEARCH_TYPE_BOOKS:
            await handle_search_books(update, context)
        elif search_type == SEARCH_TYPE_SERIES:
            await handle_search_series(update, context)
        elif search_type == SEARCH_TYPE_AUTHORS:  # Добавляем обработку поиска по авторам
            await handle_search_authors(update, context)

    except Forbidden as e:
        if "bot was blocked by the user" in str(e):
            print(f"Пользователь {update.effective_user.id} заблокировал бота")
            return
        raise e
    except Exception as e:
        print(f"Error in handle_message: {e}")
        await update.message.reply_text("❌ Произошла ошибка при обработке запроса")

    await log_stats(context)


async def handle_search_books(update: Update, context: CallbackContext):
    """Обрабатывает текстовые сообщения (поиск книг)"""
    # ОПРЕДЕЛЯЕМ ТИП СООБЩЕНИЯ
    is_edited = update.edited_message is not None
    message = update.edited_message if is_edited else update.message
    query_text = message.text
    user = message.from_user

    # ЕСЛИ СООБЩЕНИЕ ОТРЕДАКТИРОВАНО - УДАЛЯЕМ ПРЕДЫДУЩИЙ РЕЗУЛЬТАТ
    if is_edited:
        last_bot_message_id = context.user_data.get('last_bot_message_id')
        if last_bot_message_id:
            try:
                await context.bot.delete_message(
                    chat_id=message.chat_id,
                    message_id=last_bot_message_id
                )
            except Exception as e:
                print(f"Не удалось удалить старое сообщение: {e}")

    processing_msg = await message.reply_text(
        "⏰ <i>Ищу книги, ожидайте...</i>",
        parse_mode=ParseMode.HTML,
        disable_notification=True
    )

    # size_limit = context.user_data.get(SETTING_SIZE_LIMIT)
    # rating_filter = context.user_data.get(SETTING_RATING_FILTER, '')
    # search_area = context.user_data.get(SETTING_SEARCH_AREA,SETTING_SEARCH_AREA_B) # Область поиска
    # Извлекаем из БД настройки пользователя
    user_params = DB_SETTINGS.get_user_settings(user.id)
    # Сохраняем настройки пользователя в его контексте
    context.user_data[USER_PARAMS] = user_params
    # context.user_data[SEARCH_CONTEXT] = SEARCH_TYPE_BOOKS  # Сохраняем контекст

    books, found_books_count = DB_BOOKS.search_books(
        query_text, user_params.Lang, user_params.DateSortOrder, user_params.BookSize, user_params.Rating,
        search_area=user_params.SearchArea
    )

    # Проверяем, найдены ли книги
    if books or found_books_count > 0:
        pages_of_books = [books[i:i + user_params.MaxBooks] for i in range(0, len(books), user_params.MaxBooks)]

        await processing_msg.delete()

        page = 0
        keyboard = create_books_keyboard(page, pages_of_books)
        # add_close_button(keyboard)
        reply_markup = InlineKeyboardMarkup(keyboard)
        if reply_markup:
            header_found_text = form_header_books(
                page, user_params.MaxBooks, found_books_count,
                search_area=user_params.SearchArea
            )
            result_message = await message.reply_text(header_found_text, reply_markup=reply_markup)

        context.user_data[BOOKS] = books
        context.user_data[PAGES_OF_BOOKS] = pages_of_books
        context.user_data[FOUND_BOOKS_COUNT] = found_books_count
        context.user_data['last_activity'] = datetime.now()  # Сохраняем время поиска
    else:
        search_annotation_text = "ВКЛЮЧЕН" if user_params.SearchArea == SETTING_SEARCH_AREA_BA else "ВЫКЛЮЧЕН"
        result_message = await message.reply_text(
            "😞 Не нашёл подходящих книг. Попробуйте другие критерии поиска." 
            f" Обратите внимание, что в данный момент в настройках <b>{search_annotation_text}</b> поиск по аннотации книг.",
            parse_mode=ParseMode.HTML
        )

    # СОХРАНЯЕМ ID СООБЩЕНИЯ С РЕЗУЛЬТАТАМИ И ЗАПРОС
    context.user_data['last_bot_message_id'] = result_message.message_id
    context.user_data['last_search_query'] = query_text

    logger.log_user_action(user, "searched for books", f"{query_text}; count:{found_books_count}")


async def handle_search_series(update: Update, context: CallbackContext):
    """Обрабатывает текстовые сообщения (поиск книг)"""
    # ОПРЕДЕЛЯЕМ ТИП СООБЩЕНИЯ
    is_edited = update.edited_message is not None
    message = update.edited_message if is_edited else update.message
    query_text = message.text
    user = message.from_user

    # ЕСЛИ СООБЩЕНИЕ ОТРЕДАКТИРОВАНО - УДАЛЯЕМ ПРЕДЫДУЩИЙ РЕЗУЛЬТАТ
    if is_edited:
        last_bot_message_id = context.user_data.get('last_bot_message_id')
        if last_bot_message_id:
            try:
                await context.bot.delete_message(
                    chat_id=message.chat_id,
                    message_id=last_bot_message_id
                )
            except Exception as e:
                print(f"Не удалось удалить старое сообщение: {e}")

    processing_msg = await message.reply_text(
        "⏰ <i>Ищу книжные серии, ожидайте...</i>",
        parse_mode=ParseMode.HTML,
        disable_notification=True
    )

    # size_limit = context.user_data.get(SETTING_SIZE_LIMIT)
    # rating_filter = context.user_data.get(SETTING_RATING_FILTER, '')
    # search_area = context.user_data.get(SETTING_SEARCH_AREA,SETTING_SEARCH_AREA_B) # Дополнительный поиск по аннотации книг
    user_params = DB_SETTINGS.get_user_settings(user.id)
    context.user_data[USER_PARAMS] = user_params
    # context.user_data[SEARCH_CONTEXT] = SEARCH_TYPE_SERIES  # Сохраняем контекст

    # Ищем серии
    series, found_series_count = DB_BOOKS.search_series(
        query_text, user_params.Lang, user_params.BookSize, user_params.Rating,
        search_area=user_params.SearchArea
    )

    if series or found_series_count > 0:
        pages_of_series = [series[i:i + user_params.MaxBooks] for i in range(0, len(series), user_params.MaxBooks)]

        await processing_msg.delete()

        page = 0
        keyboard = create_series_keyboard(page, pages_of_series)
        # add_close_button(keyboard)
        reply_markup = InlineKeyboardMarkup(keyboard)

        if reply_markup:
            header_found_text = form_header_books(
                page, user_params.MaxBooks, found_series_count, 'серий',
                search_area=user_params.SearchArea
            )
            result_message = await message.reply_text(header_found_text, reply_markup=reply_markup)

        context.user_data[SERIES] = series
        context.user_data[PAGES_OF_SERIES] = pages_of_series
        context.user_data[FOUND_SERIES_COUNT] = found_series_count
        # context.user_data['series_search_query'] = query_text  # Сохраняем поисковый запрос
        context.user_data['last_series_page'] = page  # Сохраняем текущую страницу
        context.user_data['last_activity'] = datetime.now()  # Сохраняем время поиска
    else:
        result_message = await message.reply_text("😞 Не нашёл подходящих книжных серий. Попробуйте другие критерии поиска")

    # СОХРАНЯЕМ ID СООБЩЕНИЯ С РЕЗУЛЬТАТАМИ И ЗАПРОС
    context.user_data['last_bot_message_id'] = result_message.message_id
    context.user_data['last_search_query'] = query_text

    logger.log_user_action(user, "searched for series", f"{query_text}; count:{found_series_count}")


async def handle_search_series_books(query, context, action, params):
    """Показывает книги выбранной серии"""
    try:
        series_id = int(params[0])

        user = query.from_user
        user_params = DB_SETTINGS.get_user_settings(user.id)
        # size_limit = context.user_data.get(SETTING_SIZE_LIMIT)
        # rating_filter = context.user_data.get(SETTING_RATING_FILTER, '')
        # search_area = context.user_data.get(SETTING_SEARCH_AREA, SETTING_SEARCH_AREA_B)  # Дополнительный поиск по аннотации книг

        # Ищем книги серии в комбинации с предыдущим запросом
        # query_text = f"{context.user_data['series_search_query']}"
        query_text = f"{context.user_data['last_search_query']}"

        # print(f"DEBUG: query_text = {query_text}")

        books, found_books_count = DB_BOOKS.search_books(
            query_text, user_params.Lang, user_params.DateSortOrder, user_params.BookSize, user_params.Rating,
            series_id =series_id, #Добавляем ограничение по выбранной серии
            search_area=user_params.SearchArea
        )

        if books:
            pages_of_books = [books[i:i + user_params.MaxBooks] for i in range(0, len(books), user_params.MaxBooks)]
            context.user_data[BOOKS] = books
            context.user_data[PAGES_OF_BOOKS] = pages_of_books
            context.user_data[FOUND_BOOKS_COUNT] = found_books_count
            context.user_data['last_activity'] = datetime.now()  # Сохраняем время поиска
            # Извлекаем имя серии из данных первой книги
            series_name = books[0].SeriesTitle

            page = 0
            keyboard = create_books_keyboard(page, pages_of_books, SEARCH_TYPE_SERIES)

            # Добавляем кнопку возврата к сериям
            if keyboard:
                # add_close_button(keyboard)
                reply_markup = InlineKeyboardMarkup(keyboard)

                header_text = form_header_books(
                    page, user_params.MaxBooks, found_books_count, 'книг', series_name,
                    search_area=user_params.SearchArea
                )
                await query.edit_message_text(header_text, reply_markup=reply_markup)
        else:
            # await query.edit_message_text(f"Не найдено книг в серии '{series_name}'")
            await query.edit_message_text(f"Не найдено книг в серии '{series_id}'")

    except (ValueError, IndexError) as e:
        print(f"Ошибка при обработке серии: {e}")
        await query.edit_message_text("❌ Ошибка при загрузке серии")


async def handle_search_authors(update: Update, context: CallbackContext):
    """Обрабатывает текстовые сообщения (поиск авторов)"""
    is_edited = update.edited_message is not None
    message = update.edited_message if is_edited else update.message
    query_text = message.text
    user = message.from_user

    # ЕСЛИ СООБЩЕНИЕ ОТРЕДАКТИРОВАНО - УДАЛЯЕМ ПРЕДЫДУЩИЙ РЕЗУЛЬТАТ
    if is_edited:
        last_bot_message_id = context.user_data.get('last_bot_message_id')
        if last_bot_message_id:
            try:
                await context.bot.delete_message(
                    chat_id=message.chat_id,
                    message_id=last_bot_message_id
                )
            except Exception as e:
                print(f"Не удалось удалить старое сообщение: {e}")

    processing_msg = await message.reply_text(
        "⏰ <i>Ищу авторов, ожидайте...</i>",
        parse_mode=ParseMode.HTML,
        disable_notification=True
    )

    # size_limit = context.user_data.get(SETTING_SIZE_LIMIT)
    # rating_filter = context.user_data.get(SETTING_RATING_FILTER, '')
    # search_area = context.user_data.get(SETTING_SEARCH_AREA, SETTING_SEARCH_AREA_B) # Дополнительный поиск по аннотации книг
    user_params = DB_SETTINGS.get_user_settings(user.id)
    context.user_data[USER_PARAMS] = user_params
    # context.user_data[SEARCH_CONTEXT] = SEARCH_TYPE_AUTHORS  # Сохраняем контекст

    # Ищем авторов
    authors, found_authors_count = DB_BOOKS.search_authors(
        query_text, user_params.Lang, user_params.BookSize, user_params.Rating,
        search_area=user_params.SearchArea
    )

    if authors or found_authors_count > 0:
        pages_of_authors = [authors[i:i + user_params.MaxBooks] for i in range(0, len(authors), user_params.MaxBooks)]

        await processing_msg.delete()

        page = 0
        keyboard = create_authors_keyboard(page, pages_of_authors)
        # add_close_button(keyboard)
        reply_markup = InlineKeyboardMarkup(keyboard)

        if reply_markup:
            header_found_text = form_header_books(
                page, user_params.MaxBooks, found_authors_count, 'авторов',
                search_area=user_params.SearchArea
            )
            result_message = await message.reply_text(header_found_text, reply_markup=reply_markup)

        context.user_data[AUTHORS] = authors
        context.user_data[PAGES_OF_AUTHORS] = pages_of_authors
        context.user_data[FOUND_AUTHORS_COUNT] = found_authors_count
        # context.user_data['authors_search_query'] = query_text  # Сохраняем поисковый запрос
        context.user_data['last_authors_page'] = page  # Сохраняем текущую страницу
        context.user_data['last_activity'] = datetime.now()  # Сохраняем время поиска
    else:
        result_message = await message.reply_text("😞 Не нашёл подходящих авторов. Попробуйте другие критерии поиска")

    # СОХРАНЯЕМ ID СООБЩЕНИЯ С РЕЗУЛЬТАТАМИ И ЗАПРОС
    context.user_data['last_bot_message_id'] = result_message.message_id
    context.user_data['last_search_query'] = query_text

    logger.log_user_action(user, "searched for authors", f"{query_text}; count:{found_authors_count}")


async def handle_search_author_books(query, context, action, params):
    """Показывает книги выбранного автора"""
    try:
        author_id = int(params[0])

        user = query.from_user
        user_params = DB_SETTINGS.get_user_settings(user.id)
        # size_limit = context.user_data.get(SETTING_SIZE_LIMIT)
        # rating_filter = context.user_data.get(SETTING_RATING_FILTER, '')
        # search_area = context.user_data.get(SETTING_SEARCH_AREA, SETTING_SEARCH_AREA_B)  # Дополнительный поиск по аннотации книг

        # Ищем книги автора в комбинации с предыдущим запросом
        # query_text = f"{context.user_data['authors_search_query']}"
        query_text = f"{context.user_data['last_search_query']}"

        books, found_books_count = DB_BOOKS.search_books(
            query_text, user_params.Lang, user_params.DateSortOrder, user_params.BookSize, user_params.Rating,
            author_id = author_id, # Добавляем ограничение по автору для поиска книг выбранного автора
            search_area=user_params.SearchArea
        )

        if books:
            pages_of_books = [books[i:i + user_params.MaxBooks] for i in range(0, len(books), user_params.MaxBooks)]
            context.user_data[BOOKS] = books
            context.user_data[PAGES_OF_BOOKS] = pages_of_books
            context.user_data[FOUND_BOOKS_COUNT] = found_books_count
            context.user_data['last_activity'] = datetime.now()  # Сохраняем время поиска
            context.user_data['author_id'] = author_id # Сохраняем ID автора
            # Имя автора из первой книги
            author_name = f"{books[0].LastName} {books[0].FirstName} {books[0].MiddleName}"

            page = 0
            keyboard = create_books_keyboard(page, pages_of_books, SEARCH_TYPE_AUTHORS)
            keyboard.append([InlineKeyboardButton("👤 Об авторе", callback_data=f"author_info:{author_id}")])

            if keyboard:
                reply_markup = InlineKeyboardMarkup(keyboard)
                header_text = form_header_books(
                    page, user_params.MaxBooks, found_books_count, 'книг', author_name=author_name,
                    search_area=user_params.SearchArea
                )
                await query.edit_message_text(header_text, reply_markup=reply_markup)
        else:
            await query.edit_message_text(f"Не найдено книг автора '{author_id}'")

        logger.log_user_action(user, "searched for books", f"{query_text}; count:{found_books_count}")

    except (ValueError, IndexError) as e:
        print(f"Ошибка при обработке автора: {e}")
        await query.edit_message_text("❌ Ошибка при загрузке автора")


async def handle_page_change(query, context, action, params):
    """Обрабатывает смену страницы с проверкой данных"""
    try:
        # Проверяем, что данные поиска еще существуют
        if PAGES_OF_BOOKS not in context.user_data or not context.user_data[PAGES_OF_BOOKS]:
            await query.edit_message_text("❌ Сессия поиска истекла. Начните поиск заново.")
            return

        page = int(action.removeprefix('page_'))
        pages_of_books = context.user_data.get(PAGES_OF_BOOKS)
        # Определяем контекст поиска
        user_params = context.user_data.get(USER_PARAMS)
        # search_context = context.user_data.get(SEARCH_CONTEXT, SEARCH_TYPE_BOOKS)
        search_context = user_params.SearchType
        keyboard = create_books_keyboard(page, pages_of_books, search_context)
        if search_context == SEARCH_TYPE_AUTHORS:
            author_id = context.user_data['author_id']
            keyboard.append([InlineKeyboardButton("👤 Об авторе", callback_data=f"author_info:{author_id}")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        if reply_markup:
            found_books_count = context.user_data.get(FOUND_BOOKS_COUNT)
            # search_area = context.user_data.get(SETTING_SEARCH_AREA, SETTING_SEARCH_AREA_B)  # Дополнительный поиск по аннотации книг
            # Формируем заголовок в зависимости от контекста
            series_name = None
            if search_context == SEARCH_TYPE_SERIES:
                series_name = context.user_data.get('current_series_name', None)
            header_text = form_header_books(
                page, user_params.MaxBooks, found_books_count, 'книг', series_name,
                search_area=user_params.SearchArea
            )
            await query.edit_message_text(header_text, reply_markup=reply_markup)

    except ValueError:
        await query.answer("❌ Ошибка в номере страницы")
    except Exception as e:
        print(f"Error in page change: {e}")
        await query.answer("❌ Произошла ошибка при смене страницы")

    logger.log_user_action(query.from_user, "changed page of books", page)


async def handle_series_page_change(query, context, action, params):
    try:
        # Проверяем, что данные серий еще существуют
        if 'PAGES_OF_SERIES' not in context.user_data or not context.user_data['PAGES_OF_SERIES']:
            await query.answer("❌ Результаты поиска устарели. Выполните новый поиск.")
            await query.edit_message_text(
                "🕒 <b>Результаты поиска устарели</b>\n\n"
                "Пожалуйста, выполните новый поиск.",
                parse_mode=ParseMode.HTML
            )
            return

        page = int(action.removeprefix('series_page_'))
        pages_of_series = context.user_data.get(PAGES_OF_SERIES)
        keyboard = create_series_keyboard(page, pages_of_series)
        reply_markup = InlineKeyboardMarkup(keyboard)

        if reply_markup:
            found_series_count = context.user_data.get(FOUND_SERIES_COUNT)
            user_params = context.user_data.get(USER_PARAMS)
            # search_area = context.user_data.get(SETTING_SEARCH_AREA, SETTING_SEARCH_AREA_B)  # Дополнительный поиск по аннотации книг
            search_area = user_params.SearchArea

            header_found_text = form_header_books(
                page, user_params.MaxBooks, found_series_count,
                search_area=search_area
            )
            await query.edit_message_text(header_found_text, reply_markup=reply_markup)

        context.user_data['last_series_page'] = page  # Сохраняем текущую страницу

    except ValueError:
        await query.answer("❌ Ошибка в номере страницы")
    except Exception as e:
        print(f"Error in series page change: {e}")
        await query.answer("❌ Произошла ошибка при смене страницы")

    logger.log_user_action(query.from_user, "changed page of series", page)


async def handle_authors_page_change(query, context, action, params):
    """ Обновляем обработчик смены страниц для авторов """
    try:
        # Проверяем, что данные авторов еще существуют
        if 'PAGES_OF_AUTHORS' not in context.user_data or not context.user_data['PAGES_OF_AUTHORS']:
            await query.answer("❌ Результаты поиска устарели. Выполните новый поиск.")
            await query.edit_message_text(
                "🕒 <b>Результаты поиска устарели</b>\n\n"
                "Пожалуйста, выполните новый поиск.",
                parse_mode=ParseMode.HTML
            )
            return

        page = int(action.removeprefix('authors_page_'))
        pages_of_authors = context.user_data.get(PAGES_OF_AUTHORS)
        keyboard = create_authors_keyboard(page, pages_of_authors)
        reply_markup = InlineKeyboardMarkup(keyboard)

        if reply_markup:
            found_authors_count = context.user_data.get(FOUND_AUTHORS_COUNT)
            user_params = context.user_data.get(USER_PARAMS)
            # search_area = context.user_data.get(SETTING_SEARCH_AREA, SETTING_SEARCH_AREA_B)  # Дополнительный поиск по аннотации книг
            search_area = user_params.SearchArea

            header_found_text = form_header_books(
                page, user_params.MaxBooks, found_authors_count, 'авторов',
                search_area=search_area
            )
            await query.edit_message_text(header_found_text, reply_markup=reply_markup)

        context.user_data['last_authors_page'] = page  # Сохраняем текущую страницу

    except ValueError:
        await query.answer("❌ Ошибка в номере страницы")
    except Exception as e:
        print(f"Error in authors page change: {e}")
        await query.answer("❌ Произошла ошибка при смене страницы")

    logger.log_user_action(query.from_user, "changed page of authors", page)


# ===== НАСТРОЙКИ =====
async def show_settings_menu(update_or_query, context, from_callback=False):
    """Показывает главное меню настроек"""
    settings_keyboard = create_settings_menu()

    # Добавляем кнопку закрытия без message_id
    add_close_button(settings_keyboard)

    reply_markup = InlineKeyboardMarkup(settings_keyboard)

    if from_callback:
        await update_or_query.edit_message_text("Настроить:", reply_markup=reply_markup)
        user = update_or_query.from_user
    else:
        await update_or_query.message.reply_text("Настроить:", reply_markup=reply_markup)
        user = update_or_query.message.from_user

    logger.log_user_action(user, "showed settings menu")


async def handle_set_max_books(query, context, action, params):
    """Показывает настройки максимального вывода"""
    user_params = DB_SETTINGS.get_user_settings(query.from_user.id)
    current_value = user_params.MaxBooks

    options = SETTING_OPTIONS[SETTING_MAX_BOOKS]
    reply_markup = create_settings_keyboard(SETTING_MAX_BOOKS, current_value, options)

    await edit_or_reply_message(query, SETTING_TITLES[SETTING_MAX_BOOKS], reply_markup)
    logger.log_user_action(query.from_user, "showed max books setting for user")


async def handle_set_lang_search(query, context, action, params):
    """Показывает настройки языка поиска"""
    user_params = DB_SETTINGS.get_user_settings(query.from_user.id)
    current_value = user_params.Lang

    # Получаем языки из БД и преобразуем в нужный формат
    langs = DB_BOOKS.get_langs()
    options = [(lang[0], lang[0]) for lang in langs if lang[0]]

    reply_markup = create_settings_keyboard(SETTING_LANG_SEARCH, current_value, options)

    await edit_or_reply_message(query, SETTING_TITLES[SETTING_LANG_SEARCH], reply_markup)
    logger.log_user_action(query.from_user, "showed langs of books setting for user")


async def handle_set_sort_order(query, context, action, params):
    """Показывает настройки сортировки"""
    user_params = DB_SETTINGS.get_user_settings(query.from_user.id)
    current_value = user_params.DateSortOrder

    options = SETTING_OPTIONS[SETTING_SORT_ORDER]
    reply_markup = create_settings_keyboard(SETTING_SORT_ORDER, current_value, options)

    await edit_or_reply_message(query, SETTING_TITLES[SETTING_SORT_ORDER], reply_markup)
    logger.log_user_action(query.from_user, "showed sort order setting for user")


async def handle_set_size_limit(query, context, action, params):
    """Показывает настройки ограничения размера"""
    # current_value = context.user_data.get('size_limit', '')
    user_params = DB_SETTINGS.get_user_settings(query.from_user.id)
    current_value = user_params.BookSize

    options = SETTING_OPTIONS[SETTING_SIZE_LIMIT]
    reply_markup = create_settings_keyboard(SETTING_SIZE_LIMIT, current_value, options)

    await edit_or_reply_message(query, SETTING_TITLES[SETTING_SIZE_LIMIT], reply_markup)
    logger.log_user_action(query.from_user, "showed size limit setting for user")


async def handle_set_book_format(query, context, action, params):
    """Показывает настройки формата книг"""
    user_params = DB_SETTINGS.get_user_settings(query.from_user.id)
    current_value = user_params.BookFormat

    options = SETTING_OPTIONS[SETTING_BOOK_FORMAT]
    reply_markup = create_settings_keyboard(SETTING_BOOK_FORMAT, current_value, options)

    await edit_or_reply_message(query, SETTING_TITLES[SETTING_BOOK_FORMAT], reply_markup)
    logger.log_user_action(query.from_user, "showed book format setting for user")


async def handle_set_search_type(query, context, action, params):
    """Показывает настройки типа поиска"""
    # current_value = context.user_data.get(SETTING_SEARCH_TYPE, 'books')
    user_params = DB_SETTINGS.get_user_settings(query.from_user.id)
    current_value = user_params.SearchType

    options = SETTING_OPTIONS[SETTING_SEARCH_TYPE]
    reply_markup = create_settings_keyboard(SETTING_SEARCH_TYPE, current_value, options)

    await edit_or_reply_message(query, SETTING_TITLES[SETTING_SEARCH_TYPE], reply_markup)
    logger.log_user_action(query.from_user, "showed search type setting")


async def handle_set_rating_filter(query, context, action, params):
    """Показывает настройки фильтра по рейтингу"""
    # current_value = context.user_data.get(SETTING_RATING_FILTER, '')
    user_params = DB_SETTINGS.get_user_settings(query.from_user.id)
    current_value = user_params.Rating

    # Преобразуем текущее значение в список для отображения
    current_ratings = current_value.split(',') if current_value else []

    options = SETTING_OPTIONS[SETTING_RATING_FILTER]
    reply_markup = create_rating_filter_keyboard(current_ratings, options)

    await edit_or_reply_message(query, SETTING_TITLES[SETTING_RATING_FILTER], reply_markup)
    logger.log_user_action(query.from_user, "showed rating filter setting")


async def handle_set_actions(query, context, action, params):
    """Обрабатывает все set_ действия"""
    user = query.from_user

    # Определяем тип настройки из action
    if action.startswith(f'set_{SETTING_MAX_BOOKS}_to_'):
        setting_type = SETTING_MAX_BOOKS
        new_value = int(action.removeprefix(f'set_{SETTING_MAX_BOOKS}_to_'))
        DB_SETTINGS.update_user_settings(user.id, maxbooks=new_value)

    elif action.startswith(f'set_{SETTING_LANG_SEARCH}_to_'):
        setting_type = SETTING_LANG_SEARCH
        new_value = action.removeprefix(f'set_{SETTING_LANG_SEARCH}_to_')
        DB_SETTINGS.update_user_settings(user.id, lang=new_value)

    elif action.startswith(f'set_{SETTING_SORT_ORDER}_to_'):
        setting_type = SETTING_SORT_ORDER
        new_value = action.removeprefix(f'set_{SETTING_SORT_ORDER}_to_')
        DB_SETTINGS.update_user_settings(user.id, datesortorder=new_value)

    elif action.startswith(f'set_{SETTING_SIZE_LIMIT}_to_'):
        setting_type = SETTING_SIZE_LIMIT
        new_value = action.removeprefix(f'set_{SETTING_SIZE_LIMIT}_to_')
        # context.user_data[SETTING_SIZE_LIMIT] = new_value
        DB_SETTINGS.update_user_settings(user.id, booksize=new_value)

    elif action.startswith(f'set_{SETTING_BOOK_FORMAT}_to_'):
        setting_type = SETTING_BOOK_FORMAT
        new_value = action.removeprefix(f'set_{SETTING_BOOK_FORMAT}_to_')
        DB_SETTINGS.update_user_settings(user.id, BookFormat=new_value)

    elif action.startswith(f'set_{SETTING_SEARCH_TYPE}_to_'):
        setting_type = SETTING_SEARCH_TYPE
        new_value = action.removeprefix(f'set_{SETTING_SEARCH_TYPE}_to_')
        # context.user_data[SETTING_SEARCH_TYPE] = new_value
        DB_SETTINGS.update_user_settings(user.id, searchtype=new_value)

    elif action.startswith(f'set_{SETTING_SEARCH_AREA}_to_'):
        setting_type = SETTING_SEARCH_AREA
        new_value = action.removeprefix(f'set_{SETTING_SEARCH_AREA}_to_')
        # context.user_data[SETTING_SEARCH_AREA] = new_value
        DB_SETTINGS.update_user_settings(user.id, searcharea=new_value)

    else:
        return

    # Обновляем контекст пользователя
    # if setting_type != SETTING_SEARCH_TYPE and setting_type != SETTING_SIZE_LIMIT:
    #     context.user_data[USER_PARAMS] = DB_SETTINGS.get_user_settings(user.id)

    # Создаем обновленную клавиатуру
    if setting_type == 'lang_search':
        langs = DB_BOOKS.get_langs()
        options = [(lang[0], lang[0]) for lang in langs if lang[0]]
    else:
        options = SETTING_OPTIONS[setting_type]

    reply_markup = create_settings_keyboard(setting_type, new_value, options)

    # print(f"DEBUG: {setting_type} {new_value}")

    # Обновляем сообщение
    try:
        await query.edit_message_text(SETTING_TITLES[setting_type], reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise e

    # Логируем действие
    logger.log_user_action(user, f"set {setting_type} to {new_value}")


async def handle_set_search_area(query, context, action, params):
    """Показывает настройки дополнительного поиска"""
    # current_value = context.user_data.get(SETTING_SEARCH_AREA, SETTING_SEARCH_AREA_B)
    user_params = DB_SETTINGS.get_user_settings(query.from_user.id)
    current_value = user_params.SearchArea

    options = SETTING_OPTIONS[SETTING_SEARCH_AREA]
    reply_markup = create_settings_keyboard(SETTING_SEARCH_AREA, current_value, options)

    await edit_or_reply_message(query, SETTING_TITLES[SETTING_SEARCH_AREA], reply_markup)
    logger.log_user_action(query.from_user, "showed search area setting")


# ===== ИНФОРМАЦИЯ О КНИГАХ И АВТОРАХ =====
async def handle_book_info(query, context, action, params):
    """Показывает информацию о книге с дополнительными кнопками"""
    try:
        # file_path, file_name, file_ext = params
        file_name = params[0]
        book_id = int(file_name)

        # Получаем информацию о книге из БД
        book_info = await DB_BOOKS.get_book_info(book_id)

        if not book_info:
            await query.answer("❌ Информация о книге не найдена")
            return

        # Формируем сообщение с информацией о книге
        message_text = format_book_info(book_info)

        # print(f"DEBUG: book_info = {book_info}")
        # print(f"DEBUG: len = {len(message_text)} message_text = {message_text}")

        # Отправляем сообщение без кнопок сначала
        # Если есть обложка, отправляем фото
        if book_info.get('cover_url'):
            info_message = await query.message.reply_photo(
                photo=book_info['cover_url'],
                caption=message_text,
                parse_mode=ParseMode.HTML
            )
        else:
            info_message = await query.message.reply_text(
                message_text,
                parse_mode=ParseMode.HTML
            )

        author_ids = await DB_BOOKS.get_authors_id(book_id)

        # print(f"DEBUG: authors_ids = {author_ids}")

        # Создаем клавиатуру с дополнительными кнопками
        keyboard = [
            [InlineKeyboardButton("📥 Скачать", callback_data=f"send_file:{file_name}")],
            [InlineKeyboardButton("📖 О книге", callback_data=f"book_details:{book_id}"),
            InlineKeyboardButton("👤 Об авторе", callback_data=f"author_info:{author_ids[0]}")],
            [InlineKeyboardButton("💬 Отзывы", callback_data=f"book_reviews:{book_id}"),
            InlineKeyboardButton("❌ Закрыть", callback_data=f"close_info:{info_message.message_id}")],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await info_message.edit_reply_markup(reply_markup)

        # Сохраняем ID сообщения с информацией для возможности удаления
        context.user_data['last_book_info_message_id'] = info_message.message_id

    except Exception as e:
        print(f"Error in handle_book_info: {e}")
        await query.answer("❌ Ошибка при загрузке информации о книге")


async def handle_close_info(query, context, action, params):
    """Универсальный обработчик закрытия информационных сообщений по ID"""
    try:
        # message_id = int(params[0])
        # await context.bot.delete_message(
        #     chat_id=query.message.chat_id,
        #     message_id=message_id
        # )
        # Удаляем все переданные message_id
        for msg_id in params:
            await context.bot.delete_message(query.message.chat_id, int(msg_id))
    except Exception as e:
        print(f"Error in handle_close_info: {e}")
        await query.answer("❌ Ошибка при закрытии информации")


async def handle_book_details(query, context, action, params):
    """Показывает детальную информацию о книге с обложкой и аннотацией"""
    try:
        book_id = params[0]
        book_details = await DB_BOOKS.get_book_details(book_id)

        # print(f"DEBUG: book_details = {book_details}")

        if not book_details:
            await query.message.reply_text("❌ Аннотация о книге не найдена")
            return

        message_text = format_book_details(book_details)

        # Отправляем сообщение без кнопок сначала
        info_message = await query.message.reply_text(
            message_text,
            parse_mode=ParseMode.HTML
        )

        # Добавляем кнопку закрытия с ID сообщения
        keyboard = [[InlineKeyboardButton("❌ Закрыть", callback_data=f"close_info:{info_message.message_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await info_message.edit_reply_markup(reply_markup)

    except Exception as e:
        print(f"Error in handle_book_details: {e}")
        await query.answer("❌ Ошибка при загрузке детальной информации")


async def handle_author_info(query: CallbackQuery, context: CallbackContext, action, params):
    """Показывает информацию об авторе"""
    try:
        author_id = int(params[0])
        # print(f"DEBUG: params = {params}")
        author_info = await DB_BOOKS.get_author_info(author_id)
        # print(f"DEBUG: author_info = {author_info}")

        if not author_info:
            await query.message.reply_text("❌ Информация об авторе не найдена")
            return

        message_ids = []  # Храним ID всех сообщений
        message_text = format_author_info(author_info)

        # # Если есть фото автора, отправляем фото с укороченным текстом об авторе из-за ограничений
        # if author_info.get('photo_url'):
        #     info_message = await query.message.reply_photo(
        #         photo=author_info['photo_url'],
        #         caption=message_text[:1000] + ("..." if len(message_text) > 1000 else ""),
        #         parse_mode=ParseMode.HTML
        #     )
        # else:
        #     info_message = await query.message.reply_text(
        #         message_text,
        #         parse_mode=ParseMode.HTML
        #     )
        #
        # # Добавляем кнопку закрытия с ID сообщения
        # keyboard = [[InlineKeyboardButton("❌ Закрыть", callback_data=f"close_info:{info_message.message_id}")]]
        # reply_markup = InlineKeyboardMarkup(keyboard)
        # await info_message.edit_reply_markup(reply_markup)

        # Сообщение 1: Фото без подписи (если есть)
        if author_info.get('photo_url'):
            photo_message = await query.message.reply_photo(photo=author_info['photo_url'])
            message_ids.append(photo_message.message_id)

        # Сообщение 2: Аннотация с заголовком
        bio_message = await query.message.reply_text(message_text, parse_mode=ParseMode.HTML)
        message_ids.append(bio_message.message_id)

        # Кнопка закрытия с передачей всех message_id
        close_data = f"close_info:{':'.join(map(str, message_ids))}"
        keyboard = [[InlineKeyboardButton("❌ Закрыть", callback_data=close_data)]]
        await bio_message.edit_reply_markup(InlineKeyboardMarkup(keyboard))

    except Exception as e:
        print(f"Error in handle_author_info: {e}")
        await query.answer("❌ Ошибка при загрузке информации об авторе")


async def handle_book_reviews(query, context, action, params):
    """Показывает отзывы о книге"""
    try:
        book_id = params[0]
        reviews = await DB_BOOKS.get_book_reviews(book_id)

        if not reviews:
            await query.message.reply_text("📝 Отзывов пока нет")
            return

        message_text = format_book_reviews(reviews)
        info_message = await query.message.reply_text(
            message_text,
            parse_mode=ParseMode.HTML
        )

        # Добавляем кнопку закрытия с ID сообщения
        keyboard = [[InlineKeyboardButton("❌ Закрыть", callback_data=f"close_info:{info_message.message_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await info_message.edit_reply_markup(reply_markup)

    except Exception as e:
        print(f"Error in handle_book_reviews: {e}")
        await query.answer("❌ Ошибка при загрузке отзывов")


# ===== РАБОТА В ГРУППЕ =====
async def handle_group_message(update: Update, context: CallbackContext):
    """Обрабатывает сообщения из группы"""
    try:
        # Проверяем, обращается ли пользователь к боту
        if not is_message_for_bot(update.effective_message.text, context.bot.username):
            # Сообщение НЕ для бота - пропускаем обработку
            return

        # Обрабатываем поиск от имени пользователя
        await handle_group_search(update, context)

    except Exception as e:
        print(f"Ошибка при обработке сообщения из группы: {e}")
        # Отправляем сообщение об ошибке через context.bot
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Произошла ошибка при обработке запроса",
            reply_to_message_id=update.effective_message.message_id
        )

    await log_stats(context)


async def handle_group_search(update: Update, context: CallbackContext):
    """Обрабатывает поисковые запросы из группы"""
    try:
        # ОПРЕДЕЛЯЕМ ТИП СООБЩЕНИЯ
        is_edited = update.edited_message is not None
        message = update.edited_message if is_edited else update.message
        user = message.from_user
        chat = update.effective_chat

        # Извлекаем чистый запрос (убираем упоминание бота)
        clean_query_text = extract_clean_query(message.text, context.bot.username)

        if not clean_query_text:
            await message.reply_text(
                "❌ Пожалуйста, укажите поисковый запрос после упоминания бота",
                reply_to_message_id=message.message_id
            )
            return

        search_context_key = f"group_search_{chat.id}"
        # ЕСЛИ СООБЩЕНИЕ ОТРЕДАКТИРОВАНО - УДАЛЯЕМ ПРЕДЫДУЩИЙ РЕЗУЛЬТАТ
        if is_edited:
            last_bot_message_id = context.bot_data[search_context_key].get('last_bot_message_id')
            if last_bot_message_id:
                try:
                    await context.bot.delete_message(
                        chat_id=message.chat_id,
                        message_id=last_bot_message_id
                    )
                except Exception as e:
                    print(f"Не удалось удалить старое сообщение: {e}")

        # Отправляем сообщение о начале поиска
        processing_msg = await message.reply_text(
            f"⏰ <i>Ищу книги по запросу от {user.first_name}...</i>",
            parse_mode=ParseMode.HTML,
            reply_to_message_id=message.message_id
        )

        # Получаем или создаем настройки пользователя
        user_params = DB_SETTINGS.get_user_settings(user.id)
        # context.user_data[USER_PARAMS] = user_params
        # rating_filter = context.user_data.get(SETTING_RATING_FILTER, '')
        # search_area = context.user_data.get(SETTING_SEARCH_AREA, SETTING_SEARCH_AREA_B)  # Дополнительный поиск по аннотации книг

        print(f"DEBUG: clean_query_text = {clean_query_text}")

        # Выполняем поиск книг
        books, found_books_count = DB_BOOKS.search_books(
            clean_query_text, user_params.Lang, user_params.DateSortOrder, user_params.BookSize, user_params.Rating,
            search_area=user_params.SearchArea
        )

        # Удаляем сообщение "Ищу книги..."
        await processing_msg.delete()

        if books and found_books_count > 0:
            pages_of_books = [books[i:i + user_params.MaxBooks] for i in range(0, len(books), user_params.MaxBooks)]
            page = 0

            keyboard = create_books_keyboard(page, pages_of_books)
            # add_close_button(keyboard)
            reply_markup = InlineKeyboardMarkup(keyboard)

            if reply_markup:
                user_name = (user.first_name if user.first_name else "") #+ (f" @{user.username}" if user.username else "")
                header_found_text = f"📚 Результаты поиска" + (f" для {user_name}" if user_name else "") + ":\n\n"
                header_found_text += form_header_books(
                    page, user_params.MaxBooks, found_books_count,
                    search_area=user_params.SearchArea
                )

                # Отправляем результаты поиска
                result_message = await context.bot.send_message(
                    chat_id=chat.id,
                    text=header_found_text,
                    reply_markup=reply_markup
                )

                # Сохраняем контекст поиска в bot_data (доступно всем пользователям группы)
                context.bot_data[search_context_key] = {
                    BOOKS: books,
                    PAGES_OF_BOOKS: pages_of_books,
                    FOUND_BOOKS_COUNT: found_books_count,
                    USER_PARAMS: user_params,
                    # 'user': user,
                    'query': clean_query_text,
                    'last_activity': datetime.now(),
                    'last_bot_message_id': result_message.message_id
                }
        else:
            # Отправляем сообщение о том, что книги не найдены
            result_message = await context.bot.send_message(
                chat_id=chat.id,
                text=f"😞 Не нашёл подходящих книг для запроса '{clean_query_text}'",
                reply_to_message_id=message.message_id
            )
            # Сохраняем контекст поиска в bot_data (доступно всем пользователям группы)
            context.bot_data[search_context_key] = {
                'last_bot_message_id': result_message.message_id
            }

        logger.log_user_action(user, "searched for books in group", f"{clean_query_text}; count:{found_books_count}; chat:{chat.title}")

    except Exception as e:
        print(f"Ошибка при обработке поиска из группы: {e}")
        # Используем context.bot вместо update.message
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Произошла ошибка при поиске книг",
            reply_to_message_id=update.effective_message.message_id
        )


async def handle_group_callback(query, context, action, params, user):
    """Обрабатывает callback-запросы из групп"""
    chat_id = query.message.chat.id
    search_context_key = f"group_search_{chat_id}"

    # Восстанавливаем контекст поиска пользователя
    search_context = context.bot_data.get(search_context_key)

    if not search_context:
        await query.edit_message_text("❌ Сессия поиска истекла. Начните поиск заново.")
        return

    action_handlers = {
        'book_info': handle_book_info,
        'book_details': handle_book_details,
        'author_info': handle_author_info,
        'book_reviews': handle_book_reviews,
        'close_info': handle_close_info,
    }

    # Обрабатываем действия
    if action.startswith('page_'):
        await handle_group_page_change(query, context, action, params, user, search_context_key)
    elif action == 'send_file':
        await handle_send_file(query, context, action, params, user)
    # Прямой поиск обработчика в словаре
    elif action in action_handlers:
        handler = action_handlers[action]
        await handler(query, context, action, params)
    else:
        await query.edit_message_text("❌ Это действие недоступно в группе")

    await log_stats(context)


async def handle_group_page_change(query, context, action, params, user, search_context_key):
    """Обрабатывает смену страницы в группе"""
    chat_id = query.message.chat.id
    search_context_key = f"group_search_{chat_id}"

    # Восстанавливаем контекст поиска пользователя
    search_context = context.bot_data.get(search_context_key)

    if not search_context:
        await query.edit_message_text("❌ Сессия поиска истекла. Начните поиск заново.")
        return

    pages_of_books = search_context.get(PAGES_OF_BOOKS)
    page = int(action.removeprefix('page_'))

    if not pages_of_books or page >= len(pages_of_books):
        await query.edit_message_text("❌ Ошибка при загрузке страницы")
        return

    keyboard = create_books_keyboard(page, pages_of_books)
    reply_markup = InlineKeyboardMarkup(keyboard)

    if reply_markup:
        found_books_count = search_context.get(FOUND_BOOKS_COUNT)
        user_params = search_context.get(USER_PARAMS)
        # search_area = search_context.get(SETTING_SEARCH_AREA, SETTING_SEARCH_AREA_B)  # Дополнительный поиск по аннотации книг
        search_area = user_params.SearchArea

        user_name = (user.first_name if user.first_name else "")
        header_text = f"📚 Результаты поиска" + (f" для {user_name}" if user_name else "") + ":\n\n"
        header_text += form_header_books(
            page, user_params.MaxBooks, found_books_count,
            search_area=search_area
        )

        await query.edit_message_text(header_text, reply_markup=reply_markup)


# ===== CALLBACK ОБРАБОТЧИКИ =====
async def button_callback(update: Update, context: CallbackContext):
    """УНИВЕРСАЛЬНЫЙ обработчик callback-запросов"""
    query = update.callback_query
    user = query.from_user
    # user_params = DB_SETTINGS.get_user_settings(user.id)
    # context.user_data[USER_PARAMS] = user_params

    try:
        await query.answer()
    except BadRequest as e:
        if "Query is too old" in str(e):
            # Игнорируем устаревшие callback'ы
            return
        raise e

    data = query.data.split(':')
    action, *params = data

    # Определяем контекст (личный чат или группа)
    is_group = query.message.chat.type in ['group', 'supergroup']

    if is_group:
        # Для групп используем отдельную логику с привязкой к пользователю
        await handle_group_callback(query, context, action, params, user)
    else:
        # Сначала проверяем АДМИНСКИЕ действия
        if action in ['users_list', 'user_detail', 'toggle_block', 'recent_searches',
                      'recent_downloads', 'top_downloads', 'top_searches', 'back_to_stats',
                      'refresh_stats']:
            # Перенаправляем в админский обработчик
            from admin import handle_admin_callback
            await handle_admin_callback(update, context)
            return
        # Существующая логика для личных сообщений
        await handle_private_callback(query, context, action, params)

    await log_stats(context)


async def handle_private_callback(query, context, action, params):
    # Затем проверяем ПОЛЬЗОВАТЕЛЬСКИЕ действия
    action_handlers = {
        'send_file': handle_send_file,
        'show_genres': handle_show_genres,
        'back_to_settings': handle_back_to_settings,
        f'set_{SETTING_MAX_BOOKS}': handle_set_max_books,
        f'set_{SETTING_LANG_SEARCH}': handle_set_lang_search,
        f'set_{SETTING_SORT_ORDER}': handle_set_sort_order,
        f'set_{SETTING_SIZE_LIMIT}': handle_set_size_limit,
        f'set_{SETTING_BOOK_FORMAT}': handle_set_book_format,
        f'set_{SETTING_SEARCH_TYPE}': handle_set_search_type,
        f'set_{SETTING_RATING_FILTER}': handle_set_rating_filter,
        f'set_{SETTING_SEARCH_AREA}': handle_set_search_area,
        'show_series': handle_search_series_books,
        'back_to_series': handle_back_to_series,
        'show_author': handle_search_author_books,  # Добавляем обработчик для авторов
        'back_to_authors': handle_back_to_authors,  # Добавляем обработчик возврата к авторам
        'reset_ratings': handle_reset_ratings,
        'book_info': handle_book_info,
        'book_details': handle_book_details,
        'author_info': handle_author_info,
        'book_reviews': handle_book_reviews,
        'close_info': handle_close_info,
        'close_message': handle_close_message,
    }

    # Добавим обработку toggle рейтингов
    if action.startswith('toggle_rating_'):
        await handle_toggle_rating(query, context, action, params)
        return

    # # Добавим обработку переключения дополнительных поисков
    # if action.startswith('toggle_search_'):
    #     await handle_toggle_search(query, context, action, params)
    #     return

    # Прямой поиск обработчика в словаре
    if action in action_handlers:
        handler = action_handlers[action]
        await handler(query, context, action, params)
        return

    # Затем проверяем префиксы
    if action.startswith('page_'):
        await handle_page_change(query, context, action, params)
        return

    if action.startswith('series_page_'):
        await handle_series_page_change(query, context, action, params)
        return

    if action.startswith('authors_page_'):
        await handle_authors_page_change(query, context, action, params)
        return

    # Обработка set_ действий
    if action.startswith('set_'):
        await handle_set_actions(query, context, action, params)
        return

    # Если ничего не найдено
    print(f"Unknown action: {action}")
    await query.edit_message_text("❌ Неизвестное действие")


async def handle_send_file(query, context, action, params, for_user = None):
    """Обрабатывает отправку файла"""
    # file_path, file_name, file_ext = params
    file_name = params[0]
    book_id = file_name
    user_params = context.user_data.get(USER_PARAMS)
    book_format = user_params.BookFormat if user_params else DEFAULT_BOOK_FORMAT

    public_filename = await process_book_download(query, book_id, book_format, file_name, for_user)

    log_detail = f"{file_name}.{book_format}"
    log_detail += ":" + public_filename if public_filename else ""
    logger.log_user_action(query.from_user, "send file", log_detail)


async def handle_show_genres(query, context, action, params):
    """Показывает жанры выбранной категории"""
    try:
        genre_index = int(params[0])  # Получаем индекс

        # Получаем полный список жанров
        results = DB_BOOKS.get_parent_genres_with_counts()

        parent_genre = results[genre_index][0]  # Получаем название по индексу
        genres = DB_BOOKS.get_genres_with_counts(parent_genre)

        if genres:
            genres_html = f"<b>{parent_genre}</b>\n\n"
            for genre,count in genres:
               count_text = f" ({count:,})".replace(",", " ")  if count else " (0)"
               genres_html += f"<code>{genre}</code>{count_text}\n"
            await query.message.reply_text(genres_html, parse_mode=ParseMode.HTML)
        else:
           await query.message.reply_text("❌ Жанры не найдены для этой категории", parse_mode=ParseMode.HTML)

        logger.log_user_action(query.from_user, "show genre", parent_genre)

    except Exception as e:
        print(f"Error in handle_show_genres: {e}")
        await query.message.reply_text("❌ Ошибка при загрузке жанров")

    await log_stats(context)


async def handle_back_to_settings(query, context, action, params):
    """Возвращает в главное меню настроек"""
    await show_settings_menu(query, context, from_callback=True)


async def handle_back_to_series(query, context, action, params):
    """Возвращает к результатам поиска серий"""
    try:
        # Восстанавливаем последнюю позицию
        page_num = context.user_data.get('last_series_page', 0)

        pages_of_series = context.user_data.get(PAGES_OF_SERIES)
        if not pages_of_series:
            await query.edit_message_text("❌ Не удалось восстановить результаты поиска")
            return

        keyboard = create_series_keyboard(page_num, pages_of_series)
        reply_markup = InlineKeyboardMarkup(keyboard)

        if reply_markup:
            found_series_count = context.user_data.get(FOUND_SERIES_COUNT)
            user_params = context.user_data.get(USER_PARAMS)
            # search_area = context.user_data.get(SETTING_SEARCH_AREA, SETTING_SEARCH_AREA_B)  # Область поиска
            search_area = user_params.SearchArea

            header_found_text = form_header_books(
                page_num, user_params.MaxBooks, found_series_count, 'серий',
                search_area=search_area
            )
            await query.edit_message_text(header_found_text, reply_markup=reply_markup)
        else:
            await query.edit_message_text("❌ Не удалось восстановить результаты поиска")

    except Exception as e:
        print(f"Ошибка при возврате к сериям: {e}")
        await query.edit_message_text("❌ Ошибка при возврате к результатам поиска")


async def handle_back_to_authors(query, context, action, params):
    """Возвращает к результатам поиска авторов"""
    try:
        # Восстанавливаем последнюю позицию
        page_num = context.user_data.get('last_authors_page', 0)

        pages_of_authors = context.user_data.get(PAGES_OF_AUTHORS)
        if not pages_of_authors:
            await query.edit_message_text("❌ Не удалось восстановить результаты поиска")
            return

        keyboard = create_authors_keyboard(page_num, pages_of_authors)
        reply_markup = InlineKeyboardMarkup(keyboard)

        if reply_markup:
            found_authors_count = context.user_data.get(FOUND_AUTHORS_COUNT)
            user_params = context.user_data.get(USER_PARAMS)
            # search_area = context.user_data.get(SETTING_SEARCH_AREA, SETTING_SEARCH_AREA_B)  # Дополнительный поиск по аннотации книг
            search_area = user_params.SearchArea

            header_found_text = form_header_books(
                page_num, user_params.MaxBooks, found_authors_count, 'авторов',
                search_area=search_area
            )
            await query.edit_message_text(header_found_text, reply_markup=reply_markup)

    except Exception as e:
        print(f"Ошибка при возврате к авторам: {e}")
        await query.edit_message_text("❌ Ошибка при возврате к результатам поиска")


async def handle_close_message(query, context, action, params):
    """Закрывает меню настроек"""
    await query.delete_message()


async def handle_toggle_rating(query, context, action, params):
    """Обрабатывает переключение рейтинга в фильтре"""
    rating_value = action.removeprefix('toggle_rating_')
    # current_filter = context.user_data.get(SETTING_RATING_FILTER, '')
    user = query.from_user
    user_params = DB_SETTINGS.get_user_settings(user.id)
    current_filter = user_params.Rating
    current_ratings = current_filter.split(',') if current_filter else []

    if rating_value in current_ratings:
        # Убираем рейтинг из фильтра
        current_ratings.remove(rating_value)
    else:
        # Добавляем рейтинг в фильтр
        current_ratings.append(rating_value)

    # Обновляем фильтр
    new_filter = ','.join(current_ratings)
    # context.user_data[SETTING_RATING_FILTER] = new_filter
    DB_SETTINGS.update_user_settings(user.id, rating=new_filter)

    # Обновляем клавиатуру
    options = SETTING_OPTIONS[SETTING_RATING_FILTER]
    reply_markup = create_rating_filter_keyboard(current_ratings, options)

    try:
        await query.edit_message_text(SETTING_TITLES[SETTING_RATING_FILTER], reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise e

    logger.log_user_action(query.from_user, f"toggled rating filter: {new_filter}")


async def handle_reset_ratings(query, context, action, params):
    """Сбрасывает все выбранные рейтинги"""
    # context.user_data[SETTING_RATING_FILTER] = ''
    user = query.from_user
    DB_SETTINGS.update_user_settings(user.id, rating='')

    # Обновляем клавиатуру
    options = SETTING_OPTIONS[SETTING_RATING_FILTER]
    reply_markup = create_rating_filter_keyboard([], options)

    await query.edit_message_text(SETTING_TITLES[SETTING_RATING_FILTER], reply_markup=reply_markup)
    logger.log_user_action(query.from_user, "reset rating filter")


# ===== ПЛАТЕЖИ =====
async def send_invoice(context, chat_id, title, description, payload, currency, prices):
    await context.bot.send_invoice(
            chat_id=chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token=None,  # Обязательно None для Stars
            currency=currency,
            prices=prices,
            start_parameter="donate"  # Добавляем start_parameter
            # need_name=False,
            # need_phone_number=False,
            # need_email=False,
            # need_shipping_address=False,
            # is_flexible=False
            # max_tip_amount=5000,  # Максимальное количество звезд
            # suggested_tip_amounts=[100, 500, 1000]  # Предлагаемые суммы
        )



# def create_aux_search_keyboard(current_values, options):
#     """Создает клавиатуру для множественного выбора рейтингов"""
#     keyboard = []
#
#     for value, display_text in options:
#         is_selected = current_values.get(value, False)
#         emoji = "✔" if is_selected else ""
#         button_text = f"{emoji} {display_text}"
#
#         keyboard.append([InlineKeyboardButton(
#             button_text,
#             callback_data=f"toggle_search_{value}"
#         )])
#
#     # # Кнопка сброса
#     # keyboard.append([InlineKeyboardButton("🔄 Сбросить все", callback_data="reset_ratings")])
#
#     # Кнопка назад
#     keyboard += create_back_button()
#
#     return InlineKeyboardMarkup(keyboard)


# async def handle_toggle_search(query, context, action, params):
#     """Обрабатывает переключение режима доп. поиска"""
#     search_value = action.removeprefix('toggle_search_')
#     current_values = context.user_data.get(SETTING_AUX_SEARCH, {})
#     current_search = current_values.get(search_value, False)
#
#     current_search = not current_search
#
#     current_values[search_value] = current_search
#     context.user_data[SETTING_AUX_SEARCH] = current_values
#
#     # Обновляем клавиатуру
#     options = SETTING_OPTIONS[SETTING_AUX_SEARCH]
#     reply_markup = create_aux_search_keyboard(current_values, options)
#
#     try:
#         await query.edit_message_text(SETTING_TITLES[SETTING_AUX_SEARCH], reply_markup=reply_markup)
#     except BadRequest as e:
#         if "Message is not modified" not in str(e):
#             raise e
#
#     logger.log_user_action(query.from_user, f"toggled search: {search_value}={current_search}")
