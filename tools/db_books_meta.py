import datetime
import re
import os
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
import chardet
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
import mysql.connector
from mysql.connector import Error

PREFIX_FILE_PATH = "/media/sf_FlibustaFiles/"

# Настройки подключения к MariaDB
DB_CONFIG = {
    'host': 'localhost',
    'database': 'flibusta',  # замените на имя вашей БД
    'user': 'flibusta',  # замените на ваше имя пользователя
    'password': 'flibusta',  # замените на ваш пароль
    'charset': 'utf8mb3'
}

# Пространство имен FB2
FB2_NAMESPACE = "http://www.gribuser.ru/xml/fictionbook/2.0"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"

# Словарь с пространствами имен для использования в XPath
NAMESPACES = {
    "fb": FB2_NAMESPACE,
    "xlink": XLINK_NAMESPACE,
}


def extract_metadata_from_fb2(file):
    try:
        # Пытаемся прочитать файл с автоматическим определением кодировки
        content = file.read()

        # Определяем кодировку (если не UTF-8)
        try:
            xml_content = content.decode('utf-8')
        except UnicodeDecodeError:
            encoding = chardet.detect(content)['encoding'] or 'windows-1251'
            xml_content = content.decode(encoding, errors='replace')

        # Парсим XML с обработкой ошибок
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError:
            # Пробуем починить битый XML (базовый случай)
            xml_content = xml_content.split('<?xml', 1)[-1]  # Удаляем все до <?xml
            xml_content = '<?xml' + xml_content.split('>', 1)[0] + '>' + xml_content.split('>', 1)[1]
            root = ET.fromstring(xml_content)

        # Извлекаем метаданные
        metadata = {
            "title": None,
            "author": {
                "first_name": None,
                "last_name": None,
            },
            "publisher": None,
            "year": None,
            "city": None,
            "isbn": None,
        }

        # Название книги
        title_element = root.find(".//fb:book-title", namespaces=NAMESPACES)
        if title_element is not None:
            metadata["title"] = title_element.text

        # Автор
        first_name_element = root.find(".//fb:author/fb:first-name", namespaces=NAMESPACES)
        if first_name_element is not None:
            metadata["author"]["first_name"] = first_name_element.text

        last_name_element = root.find(".//fb:author/fb:last-name", namespaces=NAMESPACES)
        if last_name_element is not None:
            metadata["author"]["last_name"] = last_name_element.text

        # Издательство
        publisher_element = root.find(".//fb:publish-info/fb:publisher", namespaces=NAMESPACES)
        if publisher_element is not None:
            metadata["publisher"] = publisher_element.text

        # Год издания
        year_element = root.find(".//fb:publish-info/fb:year", namespaces=NAMESPACES)
        if year_element is not None:
            metadata["year"] = year_element.text

        # Город
        city_element = root.find(".//fb:publish-info/fb:city", namespaces=NAMESPACES)
        if city_element is not None:
            metadata["city"] = city_element.text

        # ISBN
        isbn_element = root.find(".//fb:publish-info/fb:isbn", namespaces=NAMESPACES)
        if isbn_element is not None:
            metadata["isbn"] = isbn_element.text
        return metadata
    except Exception as e:
        print(f"Ошибка при извлечении метаданных: {e}")
        return None
    finally:
        file.seek(0)


def process_city(city):
    """
    Обрабатывает поле city согласно требованиям:
    1) Если содержит цифры - возвращает None
    2) Удаляет все символы кроме букв (включая диакритические), пробелов, точки, запятой, минуса, дефиса
    3) Удаляет пробелы справа и слева
    4) Переводит в верхний регистр
    """
    if city is None:
        return None

    # 1) Проверяем наличие цифр
    if any(char.isdigit() for char in city):
        return None

    # 2) Удаляем все символы кроме букв (включая диакритические), пробелов, точки, запятой, минуса, дефиса
    # Используем Unicode свойства для идентификации букв (включая диакритические)
    processed_chars = []
    for char in city:
        # Проверяем, является ли символ буквой (включая диакритические)
        if unicodedata.category(char).startswith('L'):
            processed_chars.append(char)
        # Разрешаем пробелы, точку, запятую, минус, дефис
        # elif char in ' \t\n\r\f\v.,-\–—':  # пробелы, точка, запятая, разные типы дефисов
        elif char in ' \t\n\r\f\v-\–—':  # пробелы, разные типы дефисов
            processed_chars.append(char)
        # Все остальные символы игнорируем

    processed_city = ''.join(processed_chars)

    # 3) Удаляем пробелы справа и слева
    processed_city = processed_city.strip()

    # # 4) Переводим в верхний регистр
    # processed_city = processed_city.upper()

    return processed_city if processed_city else None


class BooksMetaManager:
    def __init__(self, db_config=DB_CONFIG):
        self.db_config = db_config
        self.conn = None
        self._init_db()

    def _get_connection(self):
        """Возвращает соединение с БД"""
        if self.conn is None or not self.conn.is_connected():
            try:
                self.conn = mysql.connector.connect(**self.db_config)
            except Error as e:
                print(f"Ошибка подключения к БД: {e}")
                raise
        return self.conn

    def _init_db(self):
        """Проверяет существование таблицы libbook_meta"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS `libbook_meta` (
                `BookId` int(10) unsigned NOT NULL,
                `Publisher` varchar(254) NOT NULL DEFAULT '',
                `City` varchar(254) NOT NULL DEFAULT '',
                `ISBN` varchar(254) NOT NULL DEFAULT '',
                PRIMARY KEY (`BookId`),
                KEY `Publisher` (`Publisher`),
                KEY `City` (`City`),
                KEY `ISBN` (`ISBN`)
            ) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_unicode_ci
            """)
            conn.commit()

    def close(self):
        """Закрывает соединение с БД"""
        if self.conn is not None and self.conn.is_connected():
            self.conn.close()
            self.conn = None

    def get_books_to_process(self):
        """Получает список книг для обработки из файловой системы"""
        books_to_process = []
        processed_book_ids = self._get_processed_book_ids()

        # Список проблемных книг для исключения
        PROBLEM_BOOKS = {245664, 743121, 245689, 246733, 313397, 364726, 374341, 376362}

        print("Сканирование файловой системы...")

        # Собираем все архивы
        all_archives = []
        for root_dir, dirs, files in os.walk(PREFIX_FILE_PATH):
            for file in files:
                if file.endswith('.zip'):
                    zip_path = os.path.join(root_dir, file)
                    all_archives.append(zip_path)

        # Обрабатываем архивы в прямом порядке
        for zip_path in tqdm(all_archives, desc="Поиск архивов"):
        # # Обрабатываем архивы в обратном порядке
        # for zip_path in tqdm(reversed(all_archives), desc="Поиск архивов"):
            folder = os.path.relpath(zip_path, PREFIX_FILE_PATH)

            try:
                with zipfile.ZipFile(zip_path, 'r') as zip_file:
                    # Получаем список FB2 файлов в архиве
                    fb2_files = [f for f in zip_file.namelist()
                                 if f.lower().endswith('.fb2')]

                    # Обрабатываем файлы в архиве в прямом порядке
                    for fb2_file in fb2_files:
                    # # Обрабатываем файлы в архиве в обратном порядке
                    # for fb2_file in reversed(fb2_files):
                        file_name = os.path.splitext(fb2_file)[0]
                        ext = os.path.splitext(fb2_file)[1]

                        # Проверяем, что file_name состоит только из цифр
                        if file_name.isdigit():
                            book_id = int(file_name)

                            # Пропускаем проблемные книги
                            if book_id in PROBLEM_BOOKS:
                                print(f"Пропускаем проблемную книгу: {book_id}")
                                continue

                            # Проверяем, обработана ли уже эта книга
                            if book_id not in processed_book_ids:
                                books_to_process.append({
                                    'book_id': book_id,
                                    'file_name': file_name,
                                    'ext': ext,
                                    'folder': folder
                                })
            except (zipfile.BadZipFile, OSError) as e:
                print(f"Ошибка чтения архива {file}: {e}")
                continue

        print(f"Найдено {len(books_to_process)} книг для обработки (в обратном порядке)")
        return books_to_process

    def _get_processed_book_ids(self):
        """Получает список уже обработанных BookID из БД"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT BookId FROM libbook_meta")
            result = cursor.fetchall()
            return set(book_id[0] for book_id in result)

    @staticmethod
    def process_book(book_info):
        """Обрабатывает одну книгу и возвращает метаданные"""
        book_id = book_info['book_id']
        folder = book_info['folder']
        file_name = book_info['file_name']
        ext = book_info['ext']

        # ВЫВОДИМ ИНФОРМАЦИЮ О ТЕКУЩЕЙ КНИГЕ
        print(f"Обрабатывается книга: BookID:{book_id}, File:{file_name}{ext}, Archive:{folder}")

        file_path = os.path.join(PREFIX_FILE_PATH, folder)

        try:
            with zipfile.ZipFile(file_path, 'r') as zip_file:
                fb2_file_path = f"{file_name}{ext}"

                # Проверяем наличие файла в архиве
                if fb2_file_path not in zip_file.namelist():
                    print(f"Файл {fb2_file_path} не найден в архиве {file_path}")
                    return None

                with zip_file.open(fb2_file_path) as file:
                    metadata = extract_metadata_from_fb2(file)
                    if metadata:
                        # Обрабатываем поля согласно требованиям
                        publisher = metadata.get('publisher') or ''
                        city = process_city(metadata.get('city')) or ''
                        isbn = metadata.get('isbn') or ''

                        # Ограничиваем длину строк согласно структуре таблицы
                        publisher = publisher[:254]
                        city = city[:254]
                        isbn = isbn[:254]

                        return (book_id, publisher, city, isbn)
                    else:
                        print(f"Ошибка обработки метаданных книги: BookID:{book_id}, File:{file_name}")
                        return None

        except Exception as e:
            print(f"Ошибка обработки книги {file_name}: {str(e)}")
            # Возвращаем запись с пустыми метаданными вместо None
            return (book_id, '', '', '')

    def save_metadata(self, metadata_list):
        """Сохраняет метаданные в БД"""
        if not metadata_list:
            return

        valid_metadata = [m for m in metadata_list if m is not None]
        if not valid_metadata:
            return

        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.executemany("""
                INSERT INTO libbook_meta (BookId, Publisher, City, ISBN)
                VALUES (%s, %s, %s, %s)
                """, valid_metadata)
                conn.commit()
                print(f"Сохранено {cursor.rowcount} записей")
            except Error as e:
                print(f"Ошибка сохранения в БД: {e}")
                conn.rollback()

    def update_metadata(self, batch_size=100, max_workers=4):
        """Обновляет метаданные для книг"""
        books = self.get_books_to_process()
        if not books:
            print("Все книги уже обработаны")
            return

        print(f"Найдено {len(books)} книг для обработки")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for i in tqdm(range(0, len(books), batch_size), desc="Обработка батчей"):
                batch = books[i:i + batch_size]

                # Обрабатываем батч книг
                metadata = []
                for book in tqdm(batch, desc=f"Батч {i // batch_size + 1}", leave=False):
                    result = self.process_book(book)
                    if result:
                        metadata.append(result)

                # Сохраняем батч
                if metadata:
                    self.save_metadata(metadata)

        print("Обновление метаданных завершено")

    def get_book_metadata(self, book_id):
        """Получает метаданные для конкретной книги"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT Publisher, City, ISBN
            FROM libbook_meta
            WHERE BookId = %s
            """, (book_id,))
            return cursor.fetchone()


def main():
    """Точка входа для запуска из командной строки"""
    manager = BooksMetaManager()
    try:
        manager.update_metadata()
    except Exception as e:
        print(f"Критическая ошибка: {e}")
    finally:
        manager.close()


if __name__ == "__main__":
    main()