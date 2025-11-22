from telegram import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.constants import ParseMode
from telegram.ext import CallbackContext

from database import DB_BOOKS
from utils import format_book_reviews, format_author_info, format_book_details, format_book_info

# ===== ИНФОРМАЦИЯ О КНИГАХ И АВТОРАХ =====
async def handle_book_info(query, context, action, params):
    """Показывает информацию о книге с дополнительными кнопками"""
    try:
        file_name = params[0]
        book_id = int(file_name)

        processing_msg = await query.message.reply_text(
            "⏰ <i>Ожидайте, загружаю информацию о книге...</i>",
            parse_mode=ParseMode.HTML,
            disable_notification=True
        )

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

        await processing_msg.delete()

        await info_message.edit_reply_markup(reply_markup)


    except Exception as e:
        print(f"Error in handle_book_info: {e}")
        await query.answer("❌ Ошибка при загрузке информации о книге")


async def handle_close_info(query, context, action, params):
    """Универсальный обработчик закрытия информационных сообщений по ID"""
    try:
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

        if reviews is None:
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