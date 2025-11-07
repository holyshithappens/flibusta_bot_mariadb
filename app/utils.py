import os
import re
import sys
# import xml.etree.ElementTree as ET
# import base64
from urllib.parse import unquote #, urljoin, quote
import aiohttp
#import chardet
#from bs4 import BeautifulSoup
import importlib.util
from typing import List, Dict, Any
import html

from constants import CRITERIA_PATTERN, CRITERIA_PATTERN_SERIES_QUOTED #, FLIBUSTA_DB_BOOKS_PATH  # FLIBUSTA_BASE_URL

#from html import unescape
#from constants import FLIBUSTA_BASE_URL

# Пространство имен FB2
FB2_NAMESPACE = "http://www.gribuser.ru/xml/fictionbook/2.0"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"

# Словарь с пространствами имен для использования в XPath
NAMESPACES = {
    "fb": FB2_NAMESPACE,
    "xlink": XLINK_NAMESPACE,
}


# def check_files():
#     # Проверяем доступность файлов и БД
#     required_paths = [
#         FLIBUSTA_DB_BOOKS_PATH
# #        FLIBUSTA_DB_SETTINGS_PATH
#     ]
#     for path in required_paths:
#         if not os.path.exists(path):
#             print(f"Ошибка: путь {path} недоступен в контейнере.")
#             return False
#     return True


# Имя бота из переменной окружения
BOT_USERNAME = os.getenv("BOT_USERNAME", "")

def format_size(size_in_bytes):
    units = ["B", "K", "M", "G", "T"]
    unit_index = 0
    while size_in_bytes >= 1024 and unit_index < len(units) - 1:
        size_in_bytes /= 1024
        unit_index += 1
    return f"{size_in_bytes:.1f}{units[unit_index]}"

#def split_query_into_words(query):
#    keywords = ["автор", "название", "жанр", "наименование", "писатель", "издатель"]
#    for keyword in keywords:
#        query = query.replace(keyword, "")
#    return [word.strip() for word in query.split() if len(word.strip()) > 1]

def split_word_by_control_sign(source_word):
    word = source_word.strip()
    operator = 'LIKE' # По умолчанию используется LIKE
    if len(word) > 1:
        # Определяем оператор на основе первого символа
        if word.startswith('!'):
            operator = '<>'
            word = word[1:]  # Убираем символ '!'
        elif word.startswith('='):
            operator = '='
            word = word[1:]  # Убираем символ '='
        elif word.startswith('~'):
            operator = 'NOT LIKE'
            word = word[1:]  # Убираем символ '~'

    return word, operator

def split_query_into_words(query):
    """
    Разбивает запрос на слова, учитывая специальные символы в начале слов.
    Возвращает список кортежей (слово, оператор).
    """
    #keywords = ["автор", "название", "жанр", "наименование", "писатель"]
    #for keyword in keywords:
    #    query = query.replace(keyword, "")

    words = []
    for word in query.split():
        word = word.strip()
        if len(word) > 1:
            # Определяем оператор на основе первого символа
            word, operator = split_word_by_control_sign(word)
            words.append((word, operator))
    return words

def extract_criteria(text):
    """
    Разбивает текст на критерии и свободный текст.
    Свободный текст может быть только слева или справа от критериев.
    """
    text = text.strip()
    if not text:
        return []

    # pattern = re.compile(CRITERIA_PATTERN, re.IGNORECASE)
    # # Находим все критерии
    # matches = list(re.finditer(pattern, text))

    # Сначала ищем серии в кавычках
    series_quoted_pattern = re.compile(CRITERIA_PATTERN_SERIES_QUOTED, re.IGNORECASE)
    series_quoted_matches = list(re.finditer(series_quoted_pattern, text))

    # Убираем найденные серии в кавычках из текста для дальнейшего поиска
    text_without_quoted_series = text
    for match in series_quoted_matches:
        text_without_quoted_series = text_without_quoted_series.replace(match.group(0), '')

    # Затем ищем все остальные критерии
    all_pattern = re.compile(CRITERIA_PATTERN, re.IGNORECASE)
    all_matches = list(re.finditer(all_pattern, text_without_quoted_series))

    # Определяем позицию первого и последнего критерия
    all_matches = series_quoted_matches + all_matches
    all_matches.sort(key=lambda x: x.start())

    if not all_matches:
        # Нет критериев - весь текст свободный
        return []

    #debug
    print(f"DEBUG: all_matches: {all_matches}")

    # Определяем позицию первого и последнего критерия
    first_match_start = all_matches[0].start()
    last_match_end = all_matches[-1].end()

    # Свободный текст слева от критериев
    free_text_left = text[:first_match_start].strip()
    free_text_left = free_text_left.strip(' ,;')

    # Свободный текст справа от критериев
    free_text_right = text[last_match_end:].strip()
    free_text_right = free_text_right.strip(' ,;')

    free_text = free_text_left if free_text_left else free_text_right

    criteria_values = []
    # Добавляем свободный текст как критерий "полный"
    if free_text:
        criteria_values.insert(0, ('полный', free_text))

    # Получаем значения критериев из matches
    for match in all_matches:
        criterion = match.group(1).lower()
        value = match.group(2).strip()
        criteria_values.append((criterion, value))

    # Обрабатываем все критерии (включая добавленный "полный")
    results = []
    for criterion, value in criteria_values:
        criterion = criterion.lower()
        value = value.strip()

        # ОСОБАЯ ОБРАБОТКА ДЛЯ КРИТЕРИЯ "РЕЙТИНГ"
        if criterion == 'рейтинг':
            # Обрабатываем цифры рейтинга (например: 012, 45, 5 и т.д.)
            if value.isdigit():
                # Преобразуем строку цифр в список отдельных рейтингов
                ratings = list(set(value))  # Убираем дубликаты
                for rating in ratings:
                    if rating in '012345':  # Проверяем валидность рейтинга
                        results.append((criterion, rating, '=', 'OR' if len(ratings) > 1 else 'AND'))
            continue  # Пропускаем обычную обработку для рейтинга

        # Особая обработка для критерия "серия" с кавычками
        if criterion == 'серия' and (value.startswith('"') and value.endswith('"') or
                                     value.startswith("'") and value.endswith("'")):
            # Точное совпадение для серии в кавычках
            exact_value = value[1:-1].strip()  # Убираем кавычки
            results.append((criterion, exact_value, '=', 'AND'))
        elif criterion == 'год':
            # Обработка различных форматов года
            if '-' in value:
                if value.startswith('-'):
                    # Формат: -2021 (до 2021)
                    results.append((criterion, value[1:], '<=', 'AND'))
                elif value.endswith('-'):
                    # Формат: 2021- (от 2021)
                    results.append((criterion, value[:-1], '>=', 'AND'))
                else:
                    # Формат: 2021-2023 (диапазон)
                    year_from, year_to = value.split('-')
                    results.append((criterion, year_from, '>=', 'AND'))
                    results.append((criterion, year_to, '<=', 'AND'))
            else:
                # Точно указанный год
                results.append((criterion, value, '=', 'AND'))
        else:
            # Остальные критерии (автор, название и т.д.)
            #word, operator = split_word_by_control_sign(value)
            #results.append((criterion, word, operator))

            #words = split_query_into_words(value)
            #for word, operator in words:
            #    results.append((criterion, word, operator))

            # Разбиваем значение по "|" для OR-условий
            or_parts = [part.strip() for part in value.split('|') if part.strip()]
            for part in or_parts:
                words = split_query_into_words(part)
                for word, operator in words:
                    results.append((criterion, word, operator, 'OR' if len(or_parts) > 1 else 'AND'))

    return results

# def extract_cover_from_fb2(file):
#     try:
#         # парсим FB2 файл
#         tree = ET.parse(file)
#         root = tree.getroot()
#
#         # Находим ссылку на обложку
#         cover_element = root.find(".//fb:coverpage/fb:image", namespaces=NAMESPACES)
#         if cover_element is None:
#             raise ValueError("Обложка не найдена в FB2-файле.")
#
#         cover_href = cover_element.get(f"{{{XLINK_NAMESPACE}}}href")
#         cover_id = cover_href.lstrip("#")  # Убираем символ "#"
#
#         # Находим бинарные данные обложки
#         binary_element = root.find(f".//fb:binary[@id='{cover_id}']", namespaces=NAMESPACES)
#         if binary_element is None:
#             raise ValueError(f"Бинарные данные для обложки с id '{cover_id}' не найдены.")
#
#         binary_data = binary_element.text
#         if not binary_data:
#             raise ValueError("Бинарные данные обложки пусты.")
#
#         # Декодируем Base64 в байтовый объект
#         cover_bytes = base64.b64decode(binary_data)
#         return cover_bytes
#     except Exception as e:
#         print(f"Ошибка при извлечении обложки: {e}")
#         return None
#     finally:
#         file.seek(0)

# def extract_metadata_from_fb2(file):
#     try:
#         ## Парсим XML из байтов
#         #tree = ET.parse(file)
#         #root = ET.parse(file).getroot()
#
#         # Пытаемся прочитать файл с автоматическим определением кодировки
#         content = file.read()
#
#         # Определяем кодировку (если не UTF-8)
#         try:
#             xml_content = content.decode('utf-8')
#         except UnicodeDecodeError:
#             encoding = chardet.detect(content)['encoding'] or 'windows-1251'
#             xml_content = content.decode(encoding, errors='replace')
#
#         # Парсим XML с обработкой ошибок
#         try:
#             root = ET.fromstring(xml_content)
#         except ET.ParseError:
#             # Пробуем починить битый XML (базовый случай)
#             xml_content = xml_content.split('<?xml', 1)[-1]  # Удаляем все до <?xml
#             xml_content = '<?xml' + xml_content.split('>', 1)[0] + '>' + xml_content.split('>', 1)[1]
#             root = ET.fromstring(xml_content)
#
#         # Извлекаем метаданные
#         metadata = {
#             "title": None,
#             "author": {
#                 "first_name": None,
#                 "last_name": None,
#             },
#             "publisher": None,
#             "year": None,
#             "city": None,
#             "isbn": None,
#         }
#
#         # Название книги
#         title_element = root.find(".//fb:book-title", namespaces=NAMESPACES)
#         if title_element is not None:
#             metadata["title"] = title_element.text
#
#         # Автор
#         first_name_element = root.find(".//fb:author/fb:first-name", namespaces=NAMESPACES)
#         if first_name_element is not None:
#             metadata["author"]["first_name"] = first_name_element.text
#
#         last_name_element = root.find(".//fb:author/fb:last-name", namespaces=NAMESPACES)
#         if last_name_element is not None:
#             metadata["author"]["last_name"] = last_name_element.text
#
#         # Издательство
#         publisher_element = root.find(".//fb:publish-info/fb:publisher", namespaces=NAMESPACES)
#         if publisher_element is not None:
#             metadata["publisher"] = publisher_element.text
#
#         # Год издания
#         year_element = root.find(".//fb:publish-info/fb:year", namespaces=NAMESPACES)
#         if year_element is not None:
#             metadata["year"] = year_element.text
#
#         # Город
#         city_element = root.find(".//fb:publish-info/fb:city", namespaces=NAMESPACES)
#         if city_element is not None:
#             metadata["city"] = city_element.text
#
#         # ISBN
#         isbn_element = root.find(".//fb:publish-info/fb:isbn", namespaces=NAMESPACES)
#         if isbn_element is not None:
#             metadata["isbn"] = isbn_element.text
#         return metadata
#     except Exception as e:
#         print(f"Ошибка при извлечении метаданных: {e}")
#         return None
#     finally:
#         file.seek(0)

# def format_metadata_message(metadata):
#     if metadata:
#         # Формируем сообщение с метаданными
#         message_parts = []
#         if metadata.get("publisher"):
#             #message_parts.append(f"Издательство: {metadata['publisher']}")
#             message_parts.append(f"{metadata['publisher']}")
#         if metadata.get("year"):
#             #message_parts.append(f"Год: {metadata['year']}")
#             message_parts.append(f"{metadata['year']}")
#         if metadata.get("city"):
#             #message_parts.append(f"Город: {metadata['city']}")
#             message_parts.append(f"{metadata['city']}")
#         if metadata.get("isbn"):
#             #message_parts.append(f"ISBN: {metadata['isbn']}")
#             message_parts.append(f"{metadata['isbn']}")
#         message = ", ".join(message_parts)
#     else:
#         message = None
#     return message

def remove_punctuation(text):
    if text is None:
        return None
    else:
        return re.sub(r'[^\w\s]', ' ', text)

def _get_reader_links_for_platform(platform: str) -> str:
    """
    Возвращает HTML с ссылками на читалки для конкретной платформы
    """
    if platform == 'android':
        return """
📱 <b>Читалки для Android:</b>
• 📖 <a href="https://play.google.com/store/apps/details?id=org.readera">ReadEra</a> - лучшая бесплатная
• 📚 <a href="https://play.google.com/store/apps/details?id=com.flyersoft.moonreader">Moon+ Reader</a> - мощная
• 🔥 <a href="https://play.google.com/store/apps/details?id=com.amazon.kindle">Kindle</a> - от Amazon
• 📓 <a href="https://play.google.com/store/apps/details?id=com.google.android.apps.playbooks">Google Play Книги</a>
"""
    elif platform == 'ios':
        return """
📱 <b>Читалки для iOS:</b>
• 📖 <a href="https://apps.apple.com/ru/app/readera-читалка-книг-pdf/id1441824222">ReadEra</a>
• 📚 <a href="https://apps.apple.com/ru/app/kybook-3-ebook-reader/id1259787028">KyBook 3</a>
• 🔥 <a href="https://apps.apple.com/ru/app/amazon-kindle/id302584613">Kindle</a>
• 📓 <a href="https://apps.apple.com/ru/app/apple-books/id364709193">Apple Books</a>
"""
    else:
        # Для десктопов и неизвестных платформ показываем универсальные варианты
        return """
💻 <b>Читалки для всех платформ:</b>
• 📖 <a href="https://play.google.com/store/apps/details?id=org.readera">ReadEra (Android)</a>
• 📖 <a href="https://apps.apple.com/ru/app/readera-читалка-книг-pdf/id1441824222">ReadEra (iOS)</a>
• 📚 <a href="https://www.calibre-ebook.com/">Calibre</a> - для компьютера (Windows/Mac/Linux)
• 🔥 <a href="https://www.amazon.com/b?node=16571048011">Kindle</a> - все платформы
• 📘 <a href="https://apps.apple.com/ru/app/apple-books/id364709193">Apple Books</a> (Mac/iOS)
"""

def get_platform_recommendations() -> str:
    """
    Возвращает рекомендации для всех платформ
    (универсальный подход, так как определить платформу сложно)
    """
    return """
📱 <b>Рекомендуемые читалки для всех платформ:</b>
<u>Для Android:</u>
• 📖 <a href="https://play.google.com/store/apps/details?id=org.readera">ReadEra</a> - лучшая бесплатная
• 📚 <a href="https://play.google.com/store/apps/details?id=com.flyersoft.moonreader">Moon+ Reader</a>
• 🔥 <a href="https://play.google.com/store/apps/details?id=com.amazon.kindle">Kindle</a>

<u>Для iOS:</u>
• 📖 <a href="https://apps.apple.com/ru/app/readera-читалка-книг-pdf/id1441824222">ReadEra</a>
• 📚 <a href="https://apps.apple.com/ru/app/kybook-3-ebook-reader/id1259787028">KyBook 3</a>
• 🔥 <a href="https://apps.apple.com/ru/app/amazon-kindle/id302584613">Kindle</a>

<u>Для компьютера:</u>
• 📚 <a href="https://www.calibre-ebook.com/">Calibre</a> (Windows/Mac/Linux)
• 📘 <a href="https://apps.apple.com/ru/app/apple-books/id364709193">Apple Books</a> (Mac)
• 📖 <a href="https://www.amazon.com/b?node=16571048011">Kindle</a> (все платформы)
"""


# ===== СЛУЖЕБНЫЕ ФУНКЦИИ =====

async def download_book_with_filename(url: str):
    """Скачивает книгу и возвращает данные + оригинальное имя файла"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    book_data = await response.read()
                    filename = None

                    content_disposition = response.headers.get('Content-Disposition', '')
                    if content_disposition:
                        filename_match = re.search(r'filename[^;=\n]*=([\'"]?)([^\'"\n]+)\1', content_disposition,
                                                   re.IGNORECASE)
                        if filename_match:
                            filename = unquote(filename_match.group(2))

                    return book_data, filename
                return None, None
    except Exception as e:
        print(f"Ошибка скачивания книги: {e}")
        return None, None


async def upload_to_tmpfiles(file, file_name: str) -> str:
    """Загружает файл на tmpfiles.org и возвращает URL для скачивания"""
    try:
        async with aiohttp.ClientSession() as session:
            form_data = aiohttp.FormData()
            form_data.add_field('file', file, filename=file_name)
            params = {'duration': '15m'}

            async with session.post(
                    'https://tmpfiles.org/api/v1/upload',
                    data=form_data,
                    params=params
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result['data']['url']
                return None
    except Exception as e:
        print(f"Ошибка загрузки: {e}")
        return None

# ===== ВСПОМОГАТЕЛЬНЫЕ ОБРАБОТЧИКИ ДЛЯ ГРУППОВОГО ЧАТА =====

def is_message_for_bot(message_text, bot_username):
    """Проверяет, обращается ли пользователь к боту"""
    if not bot_username:
        return False

    # Проверяем упоминание бота в начале сообщения
    return (message_text.startswith(f'@{bot_username}')
            # or message_text.startswith(f'/search@{bot_username}')
        )


def extract_clean_query(message_text, bot_username):
    """Извлекает чистый поисковый запрос из сообщения"""
    if not bot_username:
        return message_text.strip()

    # Убираем упоминание бота
    clean_text = message_text.replace(f'@{bot_username}', '').strip()
    #clean_text = clean_text.replace(f'/search@{bot_username}', '').strip()

    return clean_text


# ===== ЗАГРУЗКА НОВОСТЕЙ ИЗ PYTHON ФАЙЛА =====

async def load_bot_news(file_path: str) -> List[Dict[str, Any]]:
    """
    Загружает новости бота из Python файла
    """
    try:
        # Принудительно удаляем модуль из кэша, если он уже был загружен
        if "bot_news" in sys.modules:
            del sys.modules["bot_news"]

        # Динамически импортируем модуль с новостями
        spec = importlib.util.spec_from_file_location("bot_news", file_path)
        news_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(news_module)

        news = getattr(news_module, 'BOT_NEWS', [])
        print(f"Загружено {len(news)} новостей из {file_path}")
        return news

    except FileNotFoundError:
        print(f"Файл новостей {file_path} не найден")
        return []
    except Exception as e:
        print(f"Ошибка загрузки новостей из {file_path}: {e}")
        return []


async def get_latest_news(file_path: str, count: int = 3) -> List[Dict[str, Any]]:
    """
    Возвращает последние count новостей
    """
    all_news = await load_bot_news(file_path)
    return all_news[-count:] if all_news else []


# ===== ФОРМАТИРОВАНИЕ ВЫВОДА =====

def format_book_info(book_info):
    """Форматирует информацию о книге для сообщения"""
    # title, year, series, genre, authors = book_info

    text = f"📚 <b>{book_info['title']}</b>\n\n"
    text += f"👤 <b>Автор(ы):</b> {book_info['authors'] or 'Не указаны'}\n"
    year = book_info['year']
    series = book_info['series']
    genre = book_info['genre']
    lang = book_info['lang']
    pages = book_info['pages']
    rate = book_info['rate']
    if year and year != 0:
        text += f"📅 <b>Год:</b> {year}\n"
    if series:
        text += f"📖 <b>Серия:</b> {series}\n"
    if genre:
        text += f"📑 <b>Жанр(ы):</b> {genre}\n"
    if lang:
        text += f"🗣️ <b>Язык:</b> {lang}\n"
    if pages:
        text += f"📃 <b>Страниц:</b> {pages}\n"
    size = format_size(book_info['size'])
    text += f"📦 <b>Размер:</b> {size}\n"
    if rate:
        text += f"⭐ <b>Рейтинг:</b> {rate:.1f}"

    return text


def format_book_details(book_details):
    """Форматирует детальную информацию о книге"""
    text = f"📖 <b>Аннотация о книге:</b> {book_details.get('title', 'Неизвестно')}\n\n"
    if book_details.get('annotation'):
        # Очищаем HTML теги для телеграма
        # # clean_annotation = re.sub('<[^<]+?>', '', book_details['annotation'])  # HTML теги
        # # clean_annotation = re.sub(r'\[[^\]]*?\]', '', clean_annotation)  # Квадратные скобки
        # # clean_annotation = re.sub('&nbsp;', '', clean_annotation)  # &nbsp;
        # # # clean_annotation = book_details['annotation']
        # clean_annotation = html.escape(book_details['annotation'])
        clean_annotation = clean_html_tags(book_details['annotation'])
        text += f"{clean_annotation[:2000]}" + ("..." if len(clean_annotation) > 2000 else "")

    return text


def format_author_info(author_info):
    """Форматирует информацию об авторе"""
    text = f"👤 <b>Об авторе:</b> {author_info['name']}\n\n"
    if author_info.get('biography'):
        # # clean_bio = re.sub('<[^<]+?>', '', author_info['biography'])
        # # clean_bio = re.sub(r'\[[^\]]*?\]', '', clean_bio)  # Квадратные скобки
        # # clean_bio = re.sub('&nbsp;', '', clean_bio)  # &nbsp;
        # # # clean_bio = author_info['biography']
        # clean_bio = html.escape(author_info['biography'])
        clean_bio = clean_html_tags(author_info['biography'])
        text += f"{clean_bio[:800]}" + ("..." if len(clean_bio) > 800 else "")

    return text


def format_book_reviews(reviews):
    """Форматирует отзывы о книге"""
    text = "💬 <b>Отзывы о книге:</b>\n\n"

    for name, time, review_text in reviews[:20]:
        text += f"👤 <b>{name}</b> ({time})\n"
        # # clean_review = re.sub('<[^<]+?>', '', review_text)
        # # clean_review = re.sub(r'\[[^\]]*?\]', '', clean_review)  # Квадратные скобки
        # # clean_review = re.sub('&nbsp;', '', clean_review)  # &nbsp;
        # clean_review = html.escape(review_text)
        clean_review = clean_html_tags(review_text)
        text += f"{clean_review[:400]}" + ("..." if len(clean_review) > 400 else "") + "\n"
        # text += "─" * 20 + "\n\n"

    return text

def clean_html_tags(text):
    """Удаляем html-теги и очищаем от лишнего мусора"""
    clean_text = text
    clean_text = re.sub(r'<br\s*/?>', '\n', clean_text)  # <br> → перенос
    clean_text = re.sub(r'</?p[^>]*>', '\n', clean_text)  # <p> → перенос
    clean_text = re.sub(r'<[^<]+?>', '', clean_text)
    clean_text = re.sub(r'\[[^\]]*?\]', '', clean_text)  # Квадратные скобки
    # Убираем множественные переносы
    clean_text = re.sub(r'\n\s*\n', '\n\n', clean_text)
    clean_text = html.escape(clean_text)
    clean_text = clean_text.strip()
    return clean_text

# async def get_cover_url(book_id: str):
#     """Простой поиск обложки через BeautifulSoup"""
#     try:
#         url = f"{FLIBUSTA_BASE_URL}/b/{book_id}"
#         async with aiohttp.ClientSession() as session:
#             async with session.get(url) as response:
#                 if response.status == 200:
#                     html = await response.text()
#                     soup = BeautifulSoup(html, 'html.parser')
#                     cover_img = soup.find('img', title='Cover image')
#                     if cover_img and cover_img.get('app'):
#                         return urljoin(FLIBUSTA_BASE_URL, cover_img['app'])
#         return None
#     except Exception as e:
#         print(f"Ошибка получения обложки: {e}")
#         return None
#
#
# async def download_cover(cover_url: str):
#     """Скачивает обложку по URL"""
#     try:
#         async with aiohttp.ClientSession() as session:
#             async with session.get(cover_url) as response:
#                 if response.status == 200:
#                     return await response.read()
#         return None
#     except Exception as e:
#         print(f"Ошибка скачивания обложки: {e}")
#         return None
#
#
# async def download_book_from_flibusta(book_id: str, book_format: str):
#     """Скачивает книгу с Flibusta.is"""
#     try:
#         url = f"{FLIBUSTA_BASE_URL}/b/{book_id}/{book_format}"
#         async with aiohttp.ClientSession() as session:
#             async with session.get(url) as response:
#                 if response.status == 200:
#                     return await response.read()
#         return None
#     except Exception as e:
#         print(f"Ошибка скачивания книги: {e}")
#         return None


# # ===== DEEP LINK SEARCH =====
#
# def is_deeplink_search(args: list) -> bool:
#     """
#     Проверяет, является ли запрос deep link поиском
#     :param args: аргументы из context.args
#     :return: True если это поисковый запрос
#     """
#     return bool(args)
#
#
# def parse_deeplink_params(args: list) -> dict:
#     """
#     Парсит параметры из deep link
#     :param args: аргументы из context.args
#     :return: словарь параметров
#     """
#     params = {}
#
#     #debug
#     print(args)
#
#     for arg in args:
#         if '=' in arg:
#             key, value = arg.split('=', 1)
#             key_lower = key.lower()
#             params[key_lower] = urllib.parse.unquote(value)
#
#     return params
#
#
# def build_search_query(params: dict) -> str:
#     """
#     Строит поисковый запрос: либо из q, либо из критериев
#     """
#     # Простой поиск через q
#     if 'q' in params:
#         return params['q']
#
#     # Поиск по критериям
#     search_parts = []
#
#     for param_key, criterion in DEEPLINK_CRITERIA_MAPPING.items():
#         if params.get(param_key):
#             search_parts.append(f"{criterion}:{params[param_key]}")
#
#     return ", ".join(search_parts)
#
#
# def generate_search_deeplink(params: dict) -> str:
#     """
#     Генерирует deep link для поиска с параметрами URL
#     :param params: словарь параметров {param: value}
#     :return: готовая ссылка
#     """
#
#     if not params:
#         return f"https://t.me/{BOT_USERNAME}"
#
#     query_params = []
#     for key, value in params.items():
#         if value:
#             encoded_value = urllib.parse.quote(str(value))
#             query_params.append(f"{key}={encoded_value}")
#
#     return f"https://t.me/{BOT_USERNAME}?{'&'.join(query_params)}"
