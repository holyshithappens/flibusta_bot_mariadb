import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

from constants import FLIBUSTA_LOG_PATH
from database import  DatabaseLogs

class SingletonLogger:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize_logger()
            cls._instance._initialize_db_logger()
        return cls._instance

    def _initialize_db_logger(self):
        self.db_logger = DatabaseLogs()

    def _initialize_logger(self):
        """
        Инициализирует логгер.
        """
        self.logger = logging.getLogger('bot_logger')
        # self.logger.setLevel(logging.INFO)
        self.logger.setLevel(logging.DEBUG)

        # Формат записи логов
        # formatter = logging.Formatter('%(asctime)s - %(message)s')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        # Обработчик для записи логов в файл с ротацией по дням
        file_handler = TimedRotatingFileHandler(
            filename=FLIBUSTA_LOG_PATH + '/app.log',  # Базовое имя файла
            when='midnight',     # Ротация каждый день в полночь
            interval=1,          # Интервал ротации (1 день)
            backupCount=60,      # Хранить логи за последние 60 дней
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        file_handler.suffix = "%Y-%m-%d"  # Добавляем дату в имя файла

        # Добавляем обработчик к логгеру
        self.logger.addHandler(file_handler)

    def log_user_action(self, user, action, detail = ''):
        """
        Логирует действие пользователя.
        """
        info = f"User {user.id} ({user.username}) performed action: {action}/{detail}"

        # #debug
        print(f"DEBUG: {info}")
        # print(f"DEBUG: {user}")

        if self.logger:
            self.logger.info(info)

        if self.db_logger:
            # Получаем текущее время в формате 'YYYY-MM-DD HH:MM:SS.sssssss'
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]  # Обрезаем до 7 знаков после точки
            fullname = (f"{user.first_name}" if user.first_name else '') + (f" {user.last_name}" if user.last_name else '')
            fullname = f"({fullname.strip()})" if fullname.strip() else ''
            self.db_logger.write_user_log(timestamp, user.id, f"{user.username} {fullname}", action, detail)

    def log_system_action(self, action, detail = ''):
        """
        Логирует действие пользователя.
        """
        info = f"System action: {action}/{detail}"

        # #debug
        # print(f"DEBUG: {info}")
        # print(user)

        if self.logger:
            self.logger.info(info)

        # НЕ ПИШЕМ В БД СИСТЕМНЫЕ СООБЩЕНИЯ, ТОЛЬКО В ФАЙЛ
        # if self.db_logger:
        #     # Получаем текущее время в формате 'YYYY-MM-DD HH:MM:SS.sssssss'
        #     timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]  # Обрезаем до 7 знаков после точки
        #     self.db_logger.write_user_log(timestamp, 0, "SYSTEM", action, detail)

    def log_payment(self, payment, user):

        # Подготавливаем данные для логирования
        payment_data = {
            'payment_id': f"{payment.telegram_payment_charge_id}",
            'user_id': user.id,
            'user_name': f"{user.first_name} {user.last_name}" if user.last_name else user.first_name,
            'amount': payment.total_amount / 100,
            'currency': payment.currency,
            'payment_method': 'telegram_stars',
            'payment_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'payment_status': 'completed',
            'telegram_payment_charge_id': payment.telegram_payment_charge_id,
            'invoice_payload': payment.invoice_payload,
            'provider_payment_charge_id': payment.provider_payment_charge_id,
            'order_info': str(payment.order_info) if payment.order_info else None,
            'shipping_address': str(payment.shipping_address) if payment.shipping_address else None,
            'user_language': user.language_code,
            'refundable': True
        }

        # Логируем платеж
        self.db_logger.log_payment(payment_data)

# Создаём единственный экземпляр логгера
logger = SingletonLogger()

