import os

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, \
    ConversationHandler, CallbackContext, ContextTypes, PreCheckoutQueryHandler
from telegram.request import HTTPXRequest
from telegram.error import Forbidden, BadRequest, TimedOut

from handlers import handle_message, button_callback, start_cmd, genres_cmd, langs_cmd, settings_cmd, donate_cmd, \
    help_cmd, about_cmd, news_cmd, handle_group_message
from admin import admin_cmd, cancel_auth, auth_password, AUTH_PASSWORD, handle_admin_buttons, ADMIN_BUTTONS
from constants import CLEANUP_INTERVAL
from health import cleanup_old_sessions
from logger import logger

async def error_handler(update: Update, context: CallbackContext):
    """Глобальный обработчик ошибок"""
    error = context.error

    # Пользователь заблокировал бота
    if isinstance(error, Forbidden) and "bot was blocked by the user" in str(error):
        print(f"Пользователь заблокировал бота: {update.effective_user.id if update.effective_user else 'Unknown'}")
        return

    # Устаревший callback query
    if isinstance(error, BadRequest) and "Query is too old" in str(error):
        print(f"Устаревший callback query: {error}")
        return

    # Таймаут
    if isinstance(error, TimedOut):
        print(f"Таймаут запроса: {error}")
        return

    # Другие ошибки
    print(f"Необработанная ошибка: {error}")
    if update and update.effective_user:
        print(f"User: {update.effective_user.id}")


async def set_commands(application: Application):
    """Устанавливает меню команд"""
    commands = [
        BotCommand("start", "Запустить бота"),
        BotCommand("news", "Новости и обновления"),
        BotCommand("about", "Инфа о боте и библиотеке"),
        BotCommand("help", "Помощь по запросам"),
        BotCommand("genres", "Список жанров"),
        BotCommand("langs", "Доступные языки"),
        BotCommand("set", "Настройки поиска"),
        BotCommand("donate", "Поддержать разработчика")
    ]
    await application.bot.set_my_commands(commands)


# ==== ОБРАБОТКА ПОЛУЧЕНИЯ ДОНАТОВ ====

async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    stars_amount = payment.total_amount

    await update.message.reply_photo(
        photo='https://gifdb.com/images/high/robocop-thank-you-for-your-cooperation-gqen0zm4lhjdh14d.webp',
        caption=f"🎉 Спасибо за донат! Вы отправили {stars_amount} звёзд!\n" 
                f"Все средства пойдут на аренду VPS! ❤️")

    user = update.message.from_user
    print(f"DEBUG: Получен донат: {stars_amount} звёзд от пользователя {user.id}")
    logger.log_user_action(user.id, "received TG stars", stars_amount)



def main():


    # Получаем токен из переменной окружения
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("Токен бота не найден в переменной окружения BOT_TOKEN.")

    request = HTTPXRequest(connect_timeout=60, read_timeout=60)
    #application = Application.builder().token(TOKEN).read_timeout(60).build()
    application = Application.builder().token(TOKEN).request(request).build()

    application.add_error_handler(error_handler)

    # В первкю очередь добавляем обработчики администратора
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('admin', admin_cmd)],
        states={
            AUTH_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_password)]
        },
        fallbacks=[CommandHandler('cancel', cancel_auth)]
    )
    application.add_handler(conv_handler)

    # Регулярное выражение для фильтрации админских кнопок
    admin_buttons_regex = r'^(' + '|'.join(ADMIN_BUTTONS.values()) + ')$'
    # Обработчик для админских кнопок
    application.add_handler(MessageHandler(filters.Regex(admin_buttons_regex), handle_admin_buttons))

    # Команды пользователя
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("news", news_cmd))
    application.add_handler(CommandHandler("about", about_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("genres", genres_cmd))
    application.add_handler(CommandHandler("langs", langs_cmd))
    application.add_handler(CommandHandler("set", settings_cmd))
    application.add_handler(CommandHandler("donate", donate_cmd))
    # Обработчик ДЛЯ ГРУПП (только группы + сообщения для бота)
    application.add_handler(
        MessageHandler(filters.ChatType.GROUP & filters.TEXT, handle_group_message))
    # Обработчик ДЛЯ ЛИЧНЫХ СООБЩЕНИЙ (только приватные чаты)
    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_message))
    # Обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_callback))

    # Устанавливаем меню команд
    application.post_init = set_commands

    # Добавляем периодические задачи
    job_queue = application.job_queue
    if job_queue:
        # # Периодический мониторинг
        # job_queue.run_repeating(log_stats, interval=MONITORING_INTERVAL, first=10)
        # Периодическая очистка старых пользовательских сессий
        job_queue.run_repeating(cleanup_old_sessions, interval=CLEANUP_INTERVAL, first=CLEANUP_INTERVAL)

    application.add_handler(PreCheckoutQueryHandler(pre_checkout))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    application.run_polling()


if __name__ == '__main__':
    main()