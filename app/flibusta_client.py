import os
import aiohttp
from urllib.parse import unquote
import re
from bs4 import BeautifulSoup

from constants import FLIBUSTA_BASE_URL


class FlibustaClient:
    _base_url: str = FLIBUSTA_BASE_URL

    @classmethod
    def get_cover_url_direct(cls, local_cover_url) -> str | None:
        """Полная ссылка на обложку книги"""
        return f"{cls._base_url}/ib/{local_cover_url}" if local_cover_url else None

    @classmethod
    def get_author_photo_url(cls, local_photo_url) -> str | None:
        """Полная ссылка на фото автора"""
        return f"{cls._base_url}/ia/{local_photo_url}" if local_photo_url else None

    @classmethod
    def get_book_url(cls, book_id) -> str | None:
        """Полная ссылка на страницу книги"""
        return f"{cls._base_url}/b/{book_id}" if book_id else None

    @classmethod
    def get_download_url(cls, book_id, book_format) -> str | None:
        """Полная ссылка на страницу книги"""
        return f"{cls._base_url}/b/{book_id}/{book_format}" if book_id and book_format else None

    @classmethod
    def get_author_url(cls, author_id) -> str | None:
        """Полная ссылка на страницу книги"""
        return f"{cls._base_url}/a/{author_id}" if author_id else None

    @classmethod
    def get_genre_url(cls, genre_id) -> str | None:
        """Полная ссылка на страницу книги"""
        return f"{cls._base_url}/g/{genre_id}" if genre_id else None

    @classmethod
    def get_series_url(cls, series_id) -> str | None:
        """Полная ссылка на страницу книги"""
        return f"{cls._base_url}/s/{series_id}" if series_id else None

    @classmethod
    def get_login_url(cls) -> str:
        """Полная ссылка на страницу книги"""
        return f"{cls._base_url}/user/login"

    def __init__(self, username, password):
        self._session = None
        self._auth_session = None
        self._username = username
        self._password = password
        # self._base_url = base_url
        self._is_logged_in = False

    async def _create_session(self):
        timeout = aiohttp.ClientTimeout(total=30)
        return aiohttp.ClientSession(
            timeout=timeout,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )

    async def _get_session(self, auth=False):
        if not auth:
            if self._session is None:
                self._session = await self._create_session()
            return self._session
        else:
            if self._auth_session is None or not self._is_logged_in:
                await self.login()
            return self._auth_session
        # return await (self.auth_session() if auth else self.session())

    async def login(self):
        try:
            if self._auth_session is None:
                self._auth_session = await self._create_session()

            login_url = self.get_login_url()
            async with self._auth_session.get(login_url) as response:
                html = await response.text()

            form_build_id = None
            if 'form_build_id' in html:
                start = html.find('form_build_id') + len('form_build_id')
                start = html.find('value="', start) + len('value="')
                end = html.find('"', start)
                form_build_id = html[start:end]

            form_data = {
                'name': self._username,
                'pass': self._password,
                'form_id': 'user_login',
                'op': 'Вход в систему',
                'persistent_login': '1'
            }
            if form_build_id:
                form_data['form_build_id'] = form_build_id

            async with self._auth_session.post(login_url, data=form_data) as response:
                result_html = await response.text()

            self._is_logged_in = ('Выйти' in result_html) or (self._username in result_html)
            return self._is_logged_in

        except Exception as e:
            print(f"Ошибка авторизации: {e}")
            return False

    async def logout(self):
        if self._auth_session:
            await self._auth_session.close()
            self._auth_session = None
        self._is_logged_in = False

    # async def is_book_available(self, book_url, auth=False):
    #     session = await self._get_session(auth)
    #     try:
    #         async with session.get(book_url) as response:
    #             if response.status != 200:
    #                 return False
    #
    #             html = await response.text()
    #             if 'Страница не найдена' in html:
    #                 return False
    #             # if '/download' in html or ' (fb2) | Флибуста' in html:
    #             #     return True
    #             return True
    #     except Exception:
    #         return False

    async def download_book(self, book_id, book_format, auth=False):
        session = await self._get_session(auth)
        book_url = self.get_book_url(book_id)
        download_url = self.get_download_url(book_id, book_format)

        try:
            # # Если книга недоступна для скачивания, выходим
            # if not await self.is_book_available(book_url,auth):
            #     return None,None

            # Скачиваем книгу
            async with session.get(download_url) as response:
                if response.status != 200:
                    return None, None
                # Читаем ответ с содержимым книги
                book_data = await response.read()
                content_type = response.headers.get('Content-Type', '')

                # print(f"DEBUG: {content_type} {len(book_data)}")

                # Выходим если вместо книги сайт отправляет html с текстом "Страница не найдена"
                if 'html' in content_type:
                    html = await response.text()
                    if 'Страница не найдена' in html:
                        # print(f"DEBUG: {await response.text()}")
                        return None, None

                # Извлекаем имя файла из ответа по адресу скачивания
                filename = None
                cd = response.headers.get('Content-Disposition')
                if cd:
                    if m := re.search(r'filename[^;=\n]*=([\'"]?)([^\'"\n]+)\1', cd, re.IGNORECASE):
                        filename = unquote(m.group(2))
                # Возвращаем содержимое книги и имя файла
                return book_data, filename
        except Exception as e:
            print(f"Ошибка скачивания книги: {e}")
            return None, None

    async def close(self):
        if self._session:
            await self._session.close()
        if self._auth_session:
            await self._auth_session.close()

    async def get_book_cover_url(self, book_id: str):
        """Простой поиск обложки через BeautifulSoup"""
        try:
            url = self.get_book_url(book_id)
            # Без авторизации
            session = await self._get_session(auth=False)
            cover_url = await self._extract_cover_url_from_page(url, session)
            if cover_url:
                return cover_url
            # С авторизацией
            session = await self._get_session(auth=True)
            return await self._extract_cover_url_from_page(url, session)
        except Exception as e:
            print(f"Ошибка получения обложки: {e}")
            return None

    async def _extract_cover_url_from_page(self, url, session):
        async with session.get(url) as response:
            if response.status == 200:
                html_resp = await response.text()
                # print(f"DEBUG: html_resp = {html_resp}")
                soup = BeautifulSoup(html_resp, 'html.parser')
                # Ищем обложку по title или alt
                cover_img = soup.find('img', {'title': 'Cover image'})
                if not cover_img:
                    cover_img = soup.find('img', {'alt': 'Cover image'})

                if cover_img and cover_img.get('src'):
                    cover_url = cover_img['src']
                    if not cover_url.startswith('http'):
                        cover_url = f"{self._base_url}{cover_url}"
                    return cover_url
        return None


# Глобальный экземпляр клиента
flibusta_client = FlibustaClient(os.getenv("FLIBUSTA_USERNAME"), os.getenv("FLIBUSTA_PASSWORD"))
