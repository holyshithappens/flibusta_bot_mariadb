import asyncio

from telegram import Update, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import CallbackContext

from database import DB_BOOKS
from handlers_group import handle_group_callback
from handlers_info import handle_close_info, handle_book_reviews, handle_book_info, handle_book_details, \
    handle_author_info, add_close_button_to_message
from handlers_search import handle_authors_page_change, handle_series_page_change, handle_books_page_change, \
    handle_search_series_books, handle_search_author_books, handle_search_books
from handlers_settings import create_rating_filter_keyboard, show_settings_menu, handle_set_actions, \
    handle_set_max_books, handle_set_lang_search, handle_set_size_limit, handle_set_book_format, \
    handle_set_search_type, handle_set_rating_filter, handle_set_search_area
from handlers_utils import create_authors_keyboard, create_series_keyboard, handle_send_file
from constants import SETTING_MAX_BOOKS, SETTING_LANG_SEARCH, \
    SETTING_BOOK_FORMAT, SETTING_SEARCH_TYPE, SETTING_OPTIONS, SETTING_TITLES, SETTING_RATING_FILTER, \
    SETTING_SEARCH_AREA, SEARCH_TYPE_BOOKS, SEARCH_TYPE_SERIES, SEARCH_TYPE_AUTHORS, SETTING_SIZE_LIMIT
from context import get_pages_of_series, get_found_series_count, get_pages_of_authors, get_found_authors_count, \
    get_user_params, update_user_params, get_last_series_page, get_last_authors_page, set_switch_search, \
    get_switch_search
from flibusta_client import FlibustaClient
from utils import form_header_books
from health import log_stats
from logger import logger

# ===== CALLBACK ОБРАБОТЧИКИ =====
async def button_callback(update: Update, context: CallbackContext):
    """УНИВЕРСАЛЬНЫЙ обработчик callback-запросов"""
    # print(f"DEBUG: {context._user_id} {context._chat_id}")
    # for attr_name in dir(context):
    #     attr_value = getattr(context, attr_name)
    #     print(f"{attr_name}: {type(attr_value).__name__}")

    query = update.callback_query
    user = query.from_user

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
        await handle_private_callback(update, context, action, params)

    await log_stats(context)


async def handle_private_callback(update, context, action, params):
    query = update.callback_query
    # Затем проверяем ПОЛЬЗОВАТЕЛЬСКИЕ действия
    action_handlers = {
        'send_file': handle_send_file,
        'show_genres': handle_show_genres,
        'back_to_settings': handle_back_to_settings,
        f'set_{SETTING_MAX_BOOKS}': handle_set_max_books,
        f'set_{SETTING_LANG_SEARCH}': handle_set_lang_search,
        # f'set_{SETTING_SORT_ORDER}': handle_set_sort_order,
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

    # Прямой поиск обработчика в словаре
    if action in action_handlers:
        handler = action_handlers[action]
        # Запускаем асинхронный обработчик
        asyncio.create_task(
            handler(query, context, action, params)
        )
        return

    # Затем проверяем префиксы
    if action.startswith(f"{SEARCH_TYPE_BOOKS}_page_"):
        await handle_books_page_change(query, context, action, params)
        return

    if action.startswith(f"{SEARCH_TYPE_SERIES}_page_"):
        await handle_series_page_change(query, context, action, params)
        return

    if action.startswith(f"{SEARCH_TYPE_AUTHORS}_page_"):
        await handle_authors_page_change(query, context, action, params)
        return

    # Обработка set_ действий
    if action.startswith('set_'):
        await handle_set_actions(query, context, action, params)
        return

    # Обработка просмотра популярных книг и новинок
    if action.startswith('show_pop_'):
        await handle_show_pops(update, context, action, params)
        return

    # Если ничего не найдено
    print(f"Unknown action: {action}")
    await query.edit_message_text("❌ Неизвестное действие")


async def handle_show_genres(query, context, action, params):
    """Показывает жанры выбранной категории"""
    try:
        genre_index = int(params[0])  # Получаем genre index

        # Получаем полный список жанров
        results = DB_BOOKS.get_parent_genres_with_counts()

        parent_genre = results[genre_index][0]  # Получаем название по индексу
        # print(f"DEBUG: {genre_id}")
        genres = DB_BOOKS.get_genres_with_counts(parent_genre)
        # print(f"DEBUG: {genres}")

        if genres:
            genres_html = f"<b>{parent_genre}</b>\n\n"
            for genre_name,count,genre_id in genres:
               count_text = f" ({count:,})".replace(",", " ")  if count else " (0)"
               genre_link = FlibustaClient.get_genre_url(genre_id)
               genres_html += f"<a href='{genre_link}'>{genre_name}</a>{count_text}\n"
            genres_message = await query.message.reply_text(genres_html, parse_mode=ParseMode.HTML)
            await add_close_button_to_message(genres_message, [genres_message.message_id])
        else:
           await query.message.reply_text("❌ Жанры не найдены для этой категории", parse_mode=ParseMode.HTML)

        logger.log_user_action(query.from_user, "show genres of parent genre", parent_genre)

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
        page_num = get_last_series_page(context)
        pages_of_series = get_pages_of_series(context)
        if not pages_of_series:
            await query.edit_message_text("❌ Не удалось восстановить результаты поиска")
            return

        keyboard = create_series_keyboard(page_num, pages_of_series)
        reply_markup = InlineKeyboardMarkup(keyboard)

        if reply_markup:
            found_series_count = get_found_series_count(context)
            user_params = get_user_params(context)
            search_area = user_params.SearchArea
            show_pop = get_switch_search(context)

            header_found_text = form_header_books(
                page_num, user_params.MaxBooks, found_series_count, SEARCH_TYPE_SERIES,
                search_area=search_area,
                show_pop=show_pop
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
        page_num = get_last_authors_page(context)
        pages_of_authors = get_pages_of_authors(context)
        if not pages_of_authors:
            await query.edit_message_text("❌ Не удалось восстановить результаты поиска")
            return

        keyboard = create_authors_keyboard(page_num, pages_of_authors)
        reply_markup = InlineKeyboardMarkup(keyboard)

        if reply_markup:
            found_authors_count = get_found_authors_count(context)
            user_params = get_user_params(context)
            search_area = user_params.SearchArea
            show_pop = get_switch_search(context)

            header_found_text = form_header_books(
                page_num, user_params.MaxBooks, found_authors_count, SEARCH_TYPE_AUTHORS,
                search_area=search_area,
                show_pop=show_pop
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
    current_filter = get_user_params(context).Rating
    current_ratings = current_filter.split(',') if current_filter else []

    if rating_value in current_ratings:
        # Убираем рейтинг из фильтра
        current_ratings.remove(rating_value)
    else:
        # Добавляем рейтинг в фильтр
        current_ratings.append(rating_value)

    # Обновляем фильтр
    new_filter = ','.join(current_ratings)
    update_user_params(context, Rating=new_filter)

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
    update_user_params(context, Rating='')

    # Обновляем клавиатуру
    options = SETTING_OPTIONS[SETTING_RATING_FILTER]
    reply_markup = create_rating_filter_keyboard([], options)

    await query.edit_message_text(SETTING_TITLES[SETTING_RATING_FILTER], reply_markup=reply_markup)
    logger.log_user_action(query.from_user, "reset rating filter")


async def handle_show_pops(update, context, action, params):
    """Запуск поиска популярных книг и новинок"""
    try:
        set_switch_search(context, action)
        # await handle_message(update, context)
        await handle_search_books(update, context)

        logger.log_user_action(update.callback_query.from_user, "show populars", action)

    except Exception as e:
        print(f"Error in handle_show_pops: {e}")
        await update.callback_query.message.reply_text("❌ Ошибка при загрузке популярных книг/новинок")

    await log_stats(context)