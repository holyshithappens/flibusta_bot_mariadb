from telegram import Update
from telegram.ext import ContextTypes

from logger import logger


# ==== ОБРАБОТКА ПОЛУЧЕНИЯ ДОНАТОВ ====

async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    user = update.message.from_user

    logger.log_payment(payment, user)

    # Отправляем благодарность
    await update.message.reply_photo(
        photo='https://gifdb.com/images/high/robocop-thank-you-for-your-cooperation-gqen0zm4lhjdh14d.webp',
        caption=f"🎉 Спасибо за донат! Вы отправили {payment.total_amount} звёзд!\n"
                f"Все средства пойдут на аренду VPS! ❤️"
    )

    # Логируем действие
    logger.log_user_action(user, "payment_received",
                           f"payment_id: {payment.telegram_payment_charge_id}, "
                           f"amount: {payment.total_amount} {payment.currency}")
