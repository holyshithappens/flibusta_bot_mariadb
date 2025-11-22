import os
import re
import sys
from urllib.parse import unquote
import aiohttp
from bs4 import BeautifulSoup
import importlib.util
from typing import List, Dict, Any, Tuple
import html

from flibusta_client import FlibustaClient
from constants import  SETTING_SEARCH_AREA_B, SETTING_SEARCH_AREA_BA #FLIBUSTA_BASE_URL

# Пространство имен FB2
FB2_NAMESPACE = "http://www.gribuser.ru/xml/fictionbook/2.0"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"

# Словарь с пространствами имен для использования в XPath
NAMESPACES = {
    "fb": FB2_NAMESPACE,
    "xlink": XLINK_NAMESPACE,
}

# Имя бота из переменной окружения
BOT_USERNAME = os.getenv("BOT_USERNAME", "")


def format_size(size_in_bytes):
    units = ["B", "K", "M", "G", "T"]
    unit_index = 0
    while size_in_bytes >= 1024 and unit_index < len(units) - 1:
        size_in_bytes /= 1024
        unit_index += 1
    return f"{size_in_bytes:.1f}{units[unit_index]}"


def form_header_books(page, max_books, found_count, search_type='книг', series_name=None, author_name=None,
                      search_area=SETTING_SEARCH_AREA_B):
    """ Оформление заголовка сообщения с результатом поиска книг """
    start = max_books * page + 1
    end = min(max_books * (page + 1), found_count)

    header = f"Показываю с {start} по {end} из {found_count} найденных {search_type}"

    header += f" в серии '{series_name}'" if series_name else ""
    header += f" автора '{author_name}'" if author_name else ""
    header += " по аннотации книги" if search_area == SETTING_SEARCH_AREA_BA else ""

    return header


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

# async def download_book_with_filename(url: str):
#     """Скачивает книгу и возвращает данные + оригинальное имя файла"""
#     try:
#         async with aiohttp.ClientSession() as session:
#             async with session.get(url) as response:
#                 if response.status == 200:
#                     book_data = await response.read()
#                     filename = None
#
#                     content_disposition = response.headers.get('Content-Disposition', '')
#                     if content_disposition:
#                         filename_match = re.search(r'filename[^;=\n]*=([\'"]?)([^\'"\n]+)\1', content_disposition,
#                                                    re.IGNORECASE)
#                         if filename_match:
#                             filename = unquote(filename_match.group(2))
#
#                     return book_data, filename
#                 return None, None
#     except Exception as e:
#         print(f"Ошибка скачивания книги: {e}")
#         return None, None


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
    return message_text.startswith(f'@{bot_username}')


def extract_clean_query(message_text, bot_username):
    """Извлекает чистый поисковый запрос из сообщения"""
    if not bot_username:
        return message_text.strip()

    # Убираем упоминание бота
    clean_text = message_text.replace(f'@{bot_username}', '').strip()

    return clean_text


# ===== ЗАГРУЗКА НОВОСТЕЙ ИЗ PYTHON ФАЙЛА =====

async def load_bot_news(file_path: str) -> List[Dict[str, Any]]:
    """Загружает новости бота из Python файла"""
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
    """Возвращает последние count новостей"""
    all_news = await load_bot_news(file_path)
    return all_news[-count:] if all_news else []


# ===== ФОРМАТИРОВАНИЕ ВЫВОДА =====
def truncate_text(text, no_more_len, stop_sep) -> str:
    if len(text) <= no_more_len:
        return text
    else:
        # Обрезаем до no_more_len символов и ищем последний stop символ
        truncated = text[:no_more_len]
        last_stop_char = truncated.rfind(stop_sep)
        if last_stop_char != -1:
            return truncated[:last_stop_char] + "..."
        else:
            # Если запятых нет — значит, один очень длинный текст
             return truncated + "..."


def format_links_from_flat_string(url_routine, flat_str: str, max_num_elem: int) -> Tuple[str, bool]:
    if not flat_str:
        return "", False

    parts = [part.strip() for part in flat_str.split(',') if part.strip()]
    orig_len = len(parts)
    parts = parts[:max_num_elem]
    trunc_len = len(parts)

    # Если нечётное количество — отбрасываем последний непарный элемент
    if len(parts) % 2 != 0:
        parts = parts[:-1]

    links = []
    for i in range(0, len(parts), 2):
        try:
            elem_id = int(parts[i])
            elem_name = parts[i + 1]
            url = url_routine(elem_id)
            links.append(f"<a href='{url}'>{elem_name}</a>")
        except (ValueError, IndexError):
            # Пропускаем некорректные пары
            continue

    return ", ".join(links), orig_len != trunc_len

def format_book_info(book_info):
    """Форматирует информацию о книге для сообщения"""
    text = f"📚 <b><a href='{FlibustaClient.get_book_url(book_info['bookid'])}'>{book_info['title']}</a></b>\n"
    # authors = book_info['authors'][:300] + ("..." if len(book_info['authors']) > 300 else "")
    author_links, is_truncated = format_links_from_flat_string(FlibustaClient.get_author_url, book_info['authors'], 20)
    text += f"\n👤 <b>Автор(ы):</b> {(author_links + (',...' if is_truncated else '')) or 'Не указаны'}"
    year = book_info['year']
    series = book_info['series']
    genre_links, is_truncated = format_links_from_flat_string(FlibustaClient.get_genre_url, book_info['genres'], 10)
    lang = book_info['lang']
    pages = book_info['pages']
    rate = book_info['rate']
    # book_id = book_info['bookid']
    series_id = book_info['seqid']
    if year and year != 0:
        text += f"\n📅 <b>Год:</b> {year}"
    if series:
        text += f"\n📖 <b>Серия:</b> <a href='{FlibustaClient.get_series_url(series_id)}'>{series}</a>"
    if genre_links:
        text += f"\n📑 <b>Жанр(ы):</b> {(genre_links + (',...' if is_truncated else '')) or 'Не указаны'}"
    if lang:
        text += f"\n🗣️ <b>Язык:</b> {lang}"
    if pages:
        text += f"\n📃 <b>Страниц:</b> {pages}"
    size = format_size(book_info['size'])
    text += f"\n📦 <b>Размер:</b> {size}"
    if rate:
        text += f"\n⭐ <b>Рейтинг:</b> {rate:.1f}"
    # if book_id:
    #     text += f"\n🔑 <b>ID:</b> <a href='{FlibustaClient.get_book_url(book_id)}'>{book_id}</a>"
    return text


def format_book_details(book_details):
    """Форматирует детальную информацию о книге"""
    text = f"📖 <b>Аннотация о книге:</b> {book_details.get('title', 'Неизвестно')}\n\n"
    if book_details.get('annotation'):
        # Очищаем HTML теги для телеграма
        clean_annotation = clean_html_tags(book_details['annotation'])
        # text += f"{clean_annotation[:4000]}" + ("..." if len(clean_annotation) > 4000 else "")
        text += clean_annotation

    return truncate_text(text, 4000, '.')


def format_author_info(author_info):
    """Форматирует информацию об авторе"""
    text = f"👤 <b>Об авторе:</b> <a href='{FlibustaClient.get_author_url(author_info['author_id'])}'>{author_info['name']}</a>\n\n"
    if author_info.get('biography'):
        clean_bio = clean_html_tags(author_info['biography'])
        # text += f"{clean_bio[:4000]}" + ("..." if len(clean_bio) > 4000 else "")
        text += clean_bio

    return truncate_text(text, 4000, '.')


def format_book_reviews(reviews):
    """Форматирует отзывы о книге"""
    text = "💬 <b>Отзывы о книге:</b>\n\n"

    for name, time, review_text in reviews[:50]:
        reviewer = f"👤 <b>{name}</b> ({time})\n"
        clean_review = clean_html_tags(review_text)
        clean_review_trunc = f"{clean_review[:1000]}" + ("..." if len(clean_review) > 1000 else "") + "\n"
        if len(text + reviewer + clean_review_trunc) > 4000:
            break
        text += reviewer
        text += clean_review_trunc

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
#                     html_resp = await response.text()
#                     # print(f"DEBUG: html_resp = {html_resp}")
#                     soup = BeautifulSoup(html_resp, 'html.parser')
#                     # Ищем обложку по title или alt
#                     cover_img = soup.find('img', {'title': 'Cover image'})
#                     if not cover_img:
#                         cover_img = soup.find('img', {'alt': 'Cover image'})
#
#                     if cover_img and cover_img.get('src'):
#                         cover_url = cover_img['src']
#                         if not cover_url.startswith('http'):
#                             cover_url = f"{FLIBUSTA_BASE_URL}{cover_url}"
#                         return cover_url
#         return None
#     except Exception as e:
#         print(f"Ошибка получения обложки: {e}")
#         return None
