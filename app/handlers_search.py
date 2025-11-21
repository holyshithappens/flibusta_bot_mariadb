import asyncio
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from telegram.constants import ParseMode
from telegram.error import Forbidden
# from telegram._message import Message

from handlers_utils import create_books_keyboard, create_series_keyboard, create_authors_keyboard
from utils import form_header_books
from database import DB_BOOKS
from constants import SEARCH_TYPE_BOOKS, SEARCH_TYPE_SERIES, SEARCH_TYPE_AUTHORS, SETTING_SEARCH_AREA_BA
from context import get_user_params, get_last_bot_message_id, set_books, set_last_activity, set_last_bot_message_id, \
    set_last_search_query, set_series, set_last_series_page, get_last_search_query, set_current_series_name, \
    set_authors, set_last_authors_page, set_current_author_id, set_current_author_name, get_pages_of_books, \
    get_current_author_id, get_found_books_count, get_current_series_name, get_current_author_name, get_pages_of_series, \
    get_found_series_count, get_pages_of_authors, get_found_authors_count
from logger import logger
from health import log_stats

# ===== ПОИСК И НАВИГАЦИЯ =====
async def handle_message(update: Update, context: CallbackContext):
    """Обрабатывает текстовые сообщения (поиск книг или серий)"""
    # print(f"DEBUG: {context._user_id} {context._chat_id}")
    # for attr_name in dir(context):
    #     attr_value = getattr(context, attr_name)
    #     print(f"{attr_name}: {type(attr_value).__name__}")

    try:
        # Обрабатываем новый запрос
        user_params = get_user_params(context)
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
        # last_bot_message_id = context.user_data.get('last_bot_message_id')
        last_bot_message_id = get_last_bot_message_id(context)
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

    # Запускаем асинхронный поиск
    asyncio.create_task(
        async_search_books(context, query_text, processing_msg, user)
    )


async def async_search_books(context: CallbackContext, query_text: str, processing_msg, user):
    """Асинхронная задача поиска книг"""
    try:
        # Извлекаем из контекста или БД настройки пользователя
        user_params =  get_user_params(context)

        books = await asyncio.get_event_loop().run_in_executor(
                None,  # Используем стандартный ThreadPoolExecutor
                lambda: DB_BOOKS.search_books(
                    query_text, user_params.Lang, user_params.BookSize, user_params.Rating,
                    search_area=user_params.SearchArea
                )
        )
        found_books_count = len(books)

        # Обрабатываем результаты
        await process_search_books(context, books, found_books_count, processing_msg, query_text, user)

    except Exception as e:
        # Обработка ошибок
        await processing_msg.edit_text(f"❌ Ошибка при поиске: {str(e)}")


async def process_search_books(context: CallbackContext, books, found_books_count: int, processing_msg, query_text: str, user):
    """Обработка и отображение результатов поиска"""
    # Проверяем, найдены ли книги
    if books or found_books_count > 0:
        # Извлекаем из контекста или БД настройки пользователя
        user_params =  get_user_params(context)
        # await processing_msg.delete()
        pages_of_result = [books[i:i + user_params.MaxBooks] for i in range(0, len(books), user_params.MaxBooks)]
        page = 0

        search_type = user_params.SearchType
        keyboard = create_books_keyboard(page, pages_of_result)
        reply_markup = InlineKeyboardMarkup(keyboard)

        if reply_markup:
            header_found_text = form_header_books(
                page, user_params.MaxBooks, found_books_count,
                search_type=search_type,
                search_area=user_params.SearchArea
            )
            # result_message = await message.reply_text(header_found_text, reply_markup=reply_markup)
            # Заменяем сообщение об ожидании на результаты
            await processing_msg.edit_text(header_found_text, reply_markup=reply_markup)

            set_books(context, pages_of_result, found_books_count)
            # set_search_result(context, pages_of_result, found_books_count, search_type)
            set_last_activity(context, datetime.now()) # Сохраняем время поиска
            # СОХРАНЯЕМ ID СООБЩЕНИЯ С РЕЗУЛЬТАТАМИ И ЗАПРОС
            set_last_bot_message_id(context, processing_msg.message_id)
            set_last_search_query(context, query_text)
    else:
        # search_annotation_text = "ВКЛЮЧЕН" if user_params.SearchArea == SETTING_SEARCH_AREA_BA else "ВЫКЛЮЧЕН"
        # result_message = await message.reply_text(
        await processing_msg.edit_text(
            "😞 Не нашёл подходящих книг. Попробуйте другие критерии поиска.",
            # f" Обратите внимание, что в данный момент в настройках <b>{search_annotation_text}</b> поиск по аннотации книг.",
            parse_mode=ParseMode.HTML
        )

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
        last_bot_message_id = get_last_bot_message_id(context)
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

    # Извлекаем настройки пользователя из контекста или БД
    user_params = get_user_params(context)
    # Ищем серии
    series = DB_BOOKS.search_series(
        query_text, user_params.Lang, user_params.BookSize, user_params.Rating,
        search_area=user_params.SearchArea
    )
    found_series_count = len(series)

    if series or found_series_count > 0:
        pages_of_series = [series[i:i + user_params.MaxBooks] for i in range(0, len(series), user_params.MaxBooks)]

        await processing_msg.delete()

        page = 0
        keyboard = create_series_keyboard(page, pages_of_series)
        reply_markup = InlineKeyboardMarkup(keyboard)

        if reply_markup:
            header_found_text = form_header_books(
                page, user_params.MaxBooks, found_series_count, 'серий',
                search_area=user_params.SearchArea
            )
            result_message = await message.reply_text(header_found_text, reply_markup=reply_markup)

        set_series(context, pages_of_series, found_series_count)
        set_last_series_page(context, page)  # Сохраняем текущую страницу
        set_last_activity(context, datetime.now())  # Сохраняем время поиска
    else:
        result_message = await message.reply_text("😞 Не нашёл подходящих книжных серий. Попробуйте другие критерии поиска")

    # СОХРАНЯЕМ ID СООБЩЕНИЯ С РЕЗУЛЬТАТАМИ И ЗАПРОС
    set_last_bot_message_id(context, result_message.message_id)
    set_last_search_query(context, query_text)

    logger.log_user_action(user, "searched for series", f"{query_text}; count:{found_series_count}")


async def handle_search_series_books(query, context, action, params):
    """Показывает книги выбранной серии"""
    try:
        series_id = int(params[0])

        # Извлекаем настройки пользователя из контекста или БД
        user_params = get_user_params(context)

        # Ищем книги серии в комбинации с предыдущим запросом
        query_text = get_last_search_query(context)

        # print(f"DEBUG: query_text = {query_text}")

        books = DB_BOOKS.search_books(
            query_text, user_params.Lang, user_params.BookSize, user_params.Rating,
            search_area=user_params.SearchArea,
            series_id = series_id  # Добавляем ограничение по выбранной серии
        )
        found_books_count = len(books)

        if books:
            pages_of_books = [books[i:i + user_params.MaxBooks] for i in range(0, len(books), user_params.MaxBooks)]
            set_books(context, pages_of_books, found_books_count)
            set_last_activity(context, datetime.now())  # Сохраняем время поиска
            # Извлекаем имя серии из данных первой книги
            series_name = books[0].SeriesTitle
            set_current_series_name(context, series_name)

            page = 0
            keyboard = create_books_keyboard(page, pages_of_books, SEARCH_TYPE_SERIES)

            if keyboard:
                reply_markup = InlineKeyboardMarkup(keyboard)

                header_text = form_header_books(
                    page, user_params.MaxBooks, found_books_count, 'книг',
                    series_name=series_name,
                    search_area=user_params.SearchArea
                )
                await query.edit_message_text(header_text, reply_markup=reply_markup)
        else:
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
        last_bot_message_id = get_last_bot_message_id(context)
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

    # Извлекаем настройки пользователя из контекста или БД
    user_params = get_user_params(context)

    # Ищем авторов
    authors  = DB_BOOKS.search_authors(
        query_text, user_params.Lang, user_params.BookSize, user_params.Rating,
        search_area=user_params.SearchArea
    )
    found_authors_count = len(authors)

    if authors or found_authors_count > 0:
        pages_of_authors = [authors[i:i + user_params.MaxBooks] for i in range(0, len(authors), user_params.MaxBooks)]

        await processing_msg.delete()

        page = 0
        keyboard = create_authors_keyboard(page, pages_of_authors)
        reply_markup = InlineKeyboardMarkup(keyboard)

        if reply_markup:
            header_found_text = form_header_books(
                page, user_params.MaxBooks, found_authors_count, 'авторов',
                search_area=user_params.SearchArea
            )
            result_message = await message.reply_text(header_found_text, reply_markup=reply_markup)

        set_authors(context, pages_of_authors, found_authors_count)
        set_last_authors_page(context, page)  # Сохраняем текущую страницу
        set_last_activity(context, datetime.now())  # Сохраняем время поиска
    else:
        result_message = await message.reply_text("😞 Не нашёл подходящих авторов. Попробуйте другие критерии поиска")

    # СОХРАНЯЕМ ID СООБЩЕНИЯ С РЕЗУЛЬТАТАМИ И ЗАПРОС
    set_last_bot_message_id(context, result_message.message_id)
    set_last_search_query(context, query_text)

    logger.log_user_action(user, "searched for authors", f"{query_text}; count:{found_authors_count}")


async def handle_search_author_books(query, context, action, params):
    """Показывает книги выбранного автора"""
    try:
        author_id = int(params[0])

        user = query.from_user
        # user_params = DB_SETTINGS.get_user_settings(user.id)
        user_params = get_user_params(context)

        # Ищем книги автора в комбинации с предыдущим запросом
        query_text = get_last_search_query(context)

        books = DB_BOOKS.search_books(
            query_text, user_params.Lang, user_params.BookSize, user_params.Rating,
            search_area=user_params.SearchArea,
            author_id = author_id  # Добавляем ограничение по автору для поиска книг выбранного автора
        )
        found_books_count = len(books)

        if books:
            pages_of_books = [books[i:i + user_params.MaxBooks] for i in range(0, len(books), user_params.MaxBooks)]
            set_books(context, pages_of_books, found_books_count)
            set_last_activity(context, datetime.now())
            set_current_author_id(context, author_id)

            # Имя автора из первой книги
            author_name = f"{books[0].LastName} {books[0].FirstName} {books[0].MiddleName}"
            set_current_author_name(context, author_name)

            page = 0
            keyboard = create_books_keyboard(page, pages_of_books, SEARCH_TYPE_AUTHORS)
            keyboard.append([InlineKeyboardButton("👤 Об авторе", callback_data=f"author_info:{author_id}")])

            if keyboard:
                reply_markup = InlineKeyboardMarkup(keyboard)
                header_text = form_header_books(
                    page, user_params.MaxBooks, found_books_count, 'книг',
                    author_name=author_name,
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
        pages_of_books = get_pages_of_books(context)
        if not pages_of_books:
            await query.edit_message_text("❌ Сессия поиска истекла. Начните поиск заново.")
            return

        page = int(action.removeprefix(f"{SEARCH_TYPE_BOOKS}_page_"))
        # Определяем контекст поиска
        user_params = get_user_params(context)
        search_context = user_params.SearchType
        keyboard = create_books_keyboard(page, pages_of_books, search_context)
        if search_context == SEARCH_TYPE_AUTHORS:
            author_id = get_current_author_id(context)
            keyboard.append([InlineKeyboardButton("👤 Об авторе", callback_data=f"author_info:{author_id}")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        if reply_markup:
            found_books_count = get_found_books_count(context)
            # Формируем заголовок в зависимости от контекста
            series_name = None
            author_name = None
            if search_context == SEARCH_TYPE_SERIES:
                # series_name = context.user_data.get('current_series_name', None)
                series_name = get_current_series_name(context)
            elif search_context == SEARCH_TYPE_AUTHORS:
                author_name = get_current_author_name(context)
            header_text = form_header_books(
                page, user_params.MaxBooks, found_books_count, 'книг',
                series_name=series_name,
                author_name=author_name,
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
        pages_of_series = get_pages_of_series(context)
        if not pages_of_series:
            await query.answer("❌ Результаты поиска устарели. Выполните новый поиск.")
            await query.edit_message_text(
                "🕒 <b>Результаты поиска устарели</b>\n\n"
                "Пожалуйста, выполните новый поиск.",
                parse_mode=ParseMode.HTML
            )
            return

        page = int(action.removeprefix(f"{SEARCH_TYPE_SERIES}_page_"))
        keyboard = create_series_keyboard(page, pages_of_series)
        reply_markup = InlineKeyboardMarkup(keyboard)

        if reply_markup:
            found_series_count = get_found_series_count(context)
            user_params = get_user_params(context)
            search_area = user_params.SearchArea

            header_found_text = form_header_books(
                page, user_params.MaxBooks, found_series_count,
                search_area=search_area
            )
            await query.edit_message_text(header_found_text, reply_markup=reply_markup)

        set_last_series_page(context, page)  # Сохраняем текущую страницу

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
        pages_of_authors = get_pages_of_authors(context)
        if not pages_of_authors:
            await query.answer("❌ Результаты поиска устарели. Выполните новый поиск.")
            await query.edit_message_text(
                "🕒 <b>Результаты поиска устарели</b>\n\n"
                "Пожалуйста, выполните новый поиск.",
                parse_mode=ParseMode.HTML
            )
            return

        page = int(action.removeprefix(f"{SEARCH_TYPE_AUTHORS}_page_"))
        keyboard = create_authors_keyboard(page, pages_of_authors)
        reply_markup = InlineKeyboardMarkup(keyboard)

        if reply_markup:
            found_authors_count = get_found_authors_count(context)
            user_params = get_user_params(context)
            search_area = user_params.SearchArea

            header_found_text = form_header_books(
                page, user_params.MaxBooks, found_authors_count, 'авторов',
                search_area=search_area
            )
            await query.edit_message_text(header_found_text, reply_markup=reply_markup)

        set_last_authors_page(context, page)

    except ValueError:
        await query.answer("❌ Ошибка в номере страницы")
    except Exception as e:
        print(f"Error in authors page change: {e}")
        await query.answer("❌ Произошла ошибка при смене страницы")

    logger.log_user_action(query.from_user, "changed page of authors", page)
