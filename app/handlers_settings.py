from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import CallbackContext

from handlers_utils import add_close_button, edit_or_reply_message, create_back_button
from database import DB_BOOKS
from constants import  SETTING_MAX_BOOKS, SETTING_LANG_SEARCH, SETTING_SIZE_LIMIT, \
    SETTING_BOOK_FORMAT, SETTING_SEARCH_TYPE, SETTING_OPTIONS, SETTING_TITLES, SETTING_RATING_FILTER, BOOK_RATINGS, \
    SETTING_SEARCH_AREA
from context import get_user_params, update_user_params
from logger import logger


# ===== НАСТРОЙКИ =====
async def show_settings_menu(update_or_query, context, from_callback=False):
    """Показывает главное меню настроек"""
    settings_keyboard = create_settings_menu(context)

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
    user_params = get_user_params(context)
    current_value = user_params.MaxBooks

    options = SETTING_OPTIONS[SETTING_MAX_BOOKS]
    reply_markup = create_settings_keyboard(SETTING_MAX_BOOKS, current_value, options)

    await edit_or_reply_message(query, SETTING_TITLES[SETTING_MAX_BOOKS], reply_markup)
    logger.log_user_action(query.from_user, "showed max books setting for user")


async def handle_set_lang_search(query, context, action, params):
    """Показывает настройки языка поиска"""
    user_params = get_user_params(context)
    current_value = user_params.Lang

    # Получаем языки из БД и преобразуем в нужный формат
    langs = DB_BOOKS.get_langs()
    options = [(lang[0], lang[0]) for lang in langs if lang[0]]

    reply_markup = create_settings_keyboard(SETTING_LANG_SEARCH, current_value, options)

    await edit_or_reply_message(query, SETTING_TITLES[SETTING_LANG_SEARCH], reply_markup)
    logger.log_user_action(query.from_user, "showed langs of books setting for user")


# async def handle_set_sort_order(query, context, action, params):
#     """Показывает настройки сортировки"""
#     user_params = get_user_params(context)
#     current_value = user_params.DateSortOrder
#
#     options = SETTING_OPTIONS[SETTING_SORT_ORDER]
#     reply_markup = create_settings_keyboard(SETTING_SORT_ORDER, current_value, options)
#
#     await edit_or_reply_message(query, SETTING_TITLES[SETTING_SORT_ORDER], reply_markup)
#     logger.log_user_action(query.from_user, "showed sort order setting for user")


async def handle_set_size_limit(query, context, action, params):
    """Показывает настройки ограничения размера"""
    user_params = get_user_params(context)
    current_value = user_params.BookSize

    options = SETTING_OPTIONS[SETTING_SIZE_LIMIT]
    reply_markup = create_settings_keyboard(SETTING_SIZE_LIMIT, current_value, options)

    await edit_or_reply_message(query, SETTING_TITLES[SETTING_SIZE_LIMIT], reply_markup)
    logger.log_user_action(query.from_user, "showed size limit setting for user")


async def handle_set_book_format(query, context, action, params):
    """Показывает настройки формата книг"""
    user_params = get_user_params(context)
    current_value = user_params.BookFormat

    options = SETTING_OPTIONS[SETTING_BOOK_FORMAT]
    reply_markup = create_settings_keyboard(SETTING_BOOK_FORMAT, current_value, options)

    await edit_or_reply_message(query, SETTING_TITLES[SETTING_BOOK_FORMAT], reply_markup)
    logger.log_user_action(query.from_user, "showed book format setting for user")


async def handle_set_search_type(query, context, action, params):
    """Показывает настройки типа поиска"""
    user_params = get_user_params(context)
    current_value = user_params.SearchType

    options = SETTING_OPTIONS[SETTING_SEARCH_TYPE]
    reply_markup = create_settings_keyboard(SETTING_SEARCH_TYPE, current_value, options)

    await edit_or_reply_message(query, SETTING_TITLES[SETTING_SEARCH_TYPE], reply_markup)
    logger.log_user_action(query.from_user, "showed search type setting")


async def handle_set_rating_filter(query, context, action, params):
    """Показывает настройки фильтра по рейтингу"""
    user_params = get_user_params(context)
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
        update_user_params(context, MaxBooks=new_value)

    elif action.startswith(f'set_{SETTING_LANG_SEARCH}_to_'):
        setting_type = SETTING_LANG_SEARCH
        new_value = action.removeprefix(f'set_{SETTING_LANG_SEARCH}_to_')
        update_user_params(context, Lang=new_value)

    # elif action.startswith(f'set_{SETTING_SORT_ORDER}_to_'):
    #     setting_type = SETTING_SORT_ORDER
    #     new_value = action.removeprefix(f'set_{SETTING_SORT_ORDER}_to_')
    #     update_user_params(context, DateSortOrder=new_value)

    elif action.startswith(f'set_{SETTING_SIZE_LIMIT}_to_'):
        setting_type = SETTING_SIZE_LIMIT
        new_value = action.removeprefix(f'set_{SETTING_SIZE_LIMIT}_to_')
        update_user_params(context, BookSize=new_value)

    elif action.startswith(f'set_{SETTING_BOOK_FORMAT}_to_'):
        setting_type = SETTING_BOOK_FORMAT
        new_value = action.removeprefix(f'set_{SETTING_BOOK_FORMAT}_to_')
        update_user_params(context, BookFormat=new_value)

    elif action.startswith(f'set_{SETTING_SEARCH_TYPE}_to_'):
        setting_type = SETTING_SEARCH_TYPE
        new_value = action.removeprefix(f'set_{SETTING_SEARCH_TYPE}_to_')
        update_user_params(context, SearchType=new_value)

    elif action.startswith(f'set_{SETTING_SEARCH_AREA}_to_'):
        setting_type = SETTING_SEARCH_AREA
        new_value = action.removeprefix(f'set_{SETTING_SEARCH_AREA}_to_')
        update_user_params(context, SearchArea=new_value)

    else:
        return

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
    user_params = get_user_params(context)
    current_value = user_params.SearchArea

    options = SETTING_OPTIONS[SETTING_SEARCH_AREA]
    reply_markup = create_settings_keyboard(SETTING_SEARCH_AREA, current_value, options)

    await edit_or_reply_message(query, SETTING_TITLES[SETTING_SEARCH_AREA], reply_markup)
    logger.log_user_action(query.from_user, "showed search area setting")


def create_settings_menu(context:CallbackContext):
    """Создает главное меню настроек"""
    keyboard = []

    for setting_type, text in SETTING_TITLES.items():
        # Получаем текущее значение настройки, если передан контекст
        current_display = ""
        try:
            user_params = get_user_params(context)
            # Форматируем значение для отображения
            if setting_type == SETTING_MAX_BOOKS:
                current_value = user_params.MaxBooks
                current_display = f"({current_value})"

            elif setting_type == SETTING_LANG_SEARCH:
                current_value = user_params.Lang
                current_display = f"({current_value})" if current_value else ""

            # elif setting_type == SETTING_SORT_ORDER:
            #     # Ищем отображаемое значение в списке настроек
            #     current_value = user_params.DateSortOrder
            #     for value, display in SETTING_OPTIONS[SETTING_SORT_ORDER]:
            #         if value == current_value:
            #             current_display = f"({display})"
            #             break

            elif setting_type == SETTING_SIZE_LIMIT:
                # Ищем отображаемое значение в списке настроек
                current_value = user_params.BookSize
                for option in SETTING_OPTIONS[SETTING_SIZE_LIMIT]:
                    if option == "__NEWLINE__":
                        continue
                    value, display = option
                    if value == current_value:
                        current_display = f"({display})" if value else ""
                        break

            elif setting_type == SETTING_BOOK_FORMAT:
                # Ищем отображаемое значение в списке настроек
                current_value = user_params.BookFormat
                current_display = f"({current_value})"

            elif setting_type == SETTING_SEARCH_TYPE:
                # Ищем отображаемое значение в списке настроек
                current_value = user_params.SearchType
                for option in SETTING_OPTIONS[SETTING_SEARCH_TYPE]:
                    if option == "__NEWLINE__":
                        continue
                    value, display = option
                    if value == current_value:
                        current_display = f"({display})"
                        break

            elif setting_type == SETTING_RATING_FILTER:
                current_value = user_params.Rating
                if current_value:
                    # Для рейтинга показываем только эмодзи
                    ratings = current_value.split(',')
                    emojis = "".join([BOOK_RATINGS.get(int(r), ("⚪️", ""))[0] for r in ratings if r])
                    current_display = f"({emojis})" if emojis else ""

            elif setting_type == SETTING_SEARCH_AREA:
                # Ищем отображаемое значение в списке настроек
                current_value = user_params.SearchArea
                for option in SETTING_OPTIONS[SETTING_SEARCH_AREA]:
                    if option == "__NEWLINE__":
                        continue
                    value, display = option
                    if value == current_value:
                        current_display = f"({display})"
                        break

        except Exception as e:
            print(f"Error getting setting {setting_type}: {e}")

        button_text = f"{text} {current_display}".strip()
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"set_{setting_type}")])

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
        for option in options:
            if option == "__NEWLINE__":
                if row:  # не добавляем пустую строку
                    keyboard.append(row)
                    row = []
                continue

            value, display_text = option
            row.append(InlineKeyboardButton(
                f"{'✔️ ' if str(value) == str(current_value) else ''}{display_text}",
                callback_data=f"set_{setting_type}_to_{value}"
            ))
        if row: # Добавляем последнюю строку
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