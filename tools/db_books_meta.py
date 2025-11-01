import datetime
import re
import sqlite3
import os
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
import chardet
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor

# # Добавляем путь к src в Python path
# project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# sys.path.insert(0, project_root)
#
# from src.utils import extract_metadata_from_fb2
# #from src.constants import FLIBUSTA_DB_BOOKS_PATH  # , PREFIX_FILE_PATH

FLIBUSTA_DB_BOOKS_PATH = "/media/sf_FlibustaBot/data/Flibusta_FB2_local.hlc2"
PREFIX_FILE_PATH = "/media/sf_FlibustaFiles/"

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
        ## Парсим XML из байтов
        #tree = ET.parse(file)
        #root = ET.parse(file).getroot()

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
        #elif char in ' \t\n\r\f\v.,-\–—':  # пробелы, точка, запятая, разные типы дефисов
        elif char in ' \t\n\r\f\v-\–—':  # пробелы, разные типы дефисов
            processed_chars.append(char)
        # Все остальные символы игнорируем

    processed_city = ''.join(processed_chars)

    # 3) Удаляем пробелы справа и слева
    processed_city = processed_city.strip()

    # 4) Переводим в верхний регистр
    processed_city = processed_city.upper()

    return processed_city if processed_city else None


class BooksMetaManager:
    def __init__(self, db_path=FLIBUSTA_DB_BOOKS_PATH):
        self.db_path = db_path
        self.conn = None
        self._init_db()

    def _init_db(self):
        """Инициализирует таблицу для метаданных с минимальным набором полей"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS Books_Meta (
                BookID INTEGER PRIMARY KEY,
                Publisher TEXT,
                Year TEXT,
                City TEXT,
                ISBN TEXT,
                SearchYear INTEGER,
                SearchPublisher TEXT, 
                SearchCity TEXT,           
                FOREIGN KEY (BookID) REFERENCES Books(BookID)
            )
            """)
            conn.commit()

    def _get_connection(self):
        """Возвращает соединение с БД"""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
        return self.conn

    def close(self):
        """Закрывает соединение с БД"""
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def get_books_to_process(self, limit=None):
        """Получает список книг для обработки"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = """
            SELECT b.BookID, b.Folder, b.FileName, b.Ext 
            FROM Books b
            LEFT JOIN Books_Meta m ON b.BookID = m.BookID
            WHERE m.BookID IS NULL
            """
            if limit:
                query += f" LIMIT {limit}"
            cursor.execute(query)
            return cursor.fetchall()

    @staticmethod
    def process_book(book_info):
        """Обрабатывает одну книгу и возвращает только необходимые метаданные"""
        book_id, folder, file_name, ext = book_info
        file_path = os.path.join(PREFIX_FILE_PATH, folder)

        try:
            with zipfile.ZipFile(file_path, 'r') as zip_file:
                with zip_file.open(f"{file_name}{ext}") as file:
                    metadata = extract_metadata_from_fb2(file)
                    if metadata:
                        # Безопасное преобразование в верхний регистр
                        publisher = metadata.get('publisher')
                        city = metadata.get('city')
                        year = metadata.get('year')

                        # Обрабатываем поля для поиска с помощью process_city
                        search_publisher = publisher.upper() if publisher else None
                        search_city = process_city(city) if city else None
                        search_year = year if year else None

                        return (
                            book_id,
                            publisher,
                            metadata.get('year'),
                            city,
                            metadata.get('isbn'),
                            search_year,
                            search_publisher,
                            search_city
                        )
                    else:
                        print(f"Ошибка обработки метаданных книги: Book_ID:{book_id}, Folder:{folder}, Filename:{file_name}")
        except Exception as e:
            print(f"Ошибка обработки книги {file_name}: {str(e)}")
            return None

    def save_metadata(self, metadata_list):
        """Сохраняет метаданные в БД"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
            INSERT INTO Books_Meta (
                BookID, Publisher, Year, City, ISBN, SearchYear, SearchPublisher, SearchCity
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [m for m in metadata_list if m is not None])
            conn.commit()

    def update_metadata(self, batch_size=1000, max_workers=4):
        """Обновляет метаданные для книг"""
        books = self.get_books_to_process()
        if not books:
            print("Все книги уже обработаны")
            return

        print(f"Найдено {len(books)} книг для обработки")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for i in tqdm(range(0, len(books), batch_size)):
                batch = books[i:i + batch_size]
                metadata = list(tqdm(
                    executor.map(self.process_book, batch),
                    total=len(batch),
                    desc="Обработка книг"
                ))
                self.save_metadata(metadata)

        print("Обновление метаданных завершено")

    def get_book_metadata(self, book_id):
        """Получает метаданные для конкретной книги"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT Publisher, Year, City, ISBN
            FROM Books_Meta
            WHERE BookID = ?
            """, (book_id,))
            return cursor.fetchone()


def main():
    """Точка входа для запуска из командной строки"""
    manager = BooksMetaManager()
    try:
        manager.update_metadata()
    finally:
        manager.close()


if __name__ == "__main__":
    main()