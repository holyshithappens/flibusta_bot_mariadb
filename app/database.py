import os
import sqlite3
from collections import namedtuple
from typing import Dict, List

import mysql.connector
from contextlib import contextmanager

from constants import FLIBUSTA_DB_SETTINGS_PATH, FLIBUSTA_DB_LOGS_PATH, SEARCH_CRITERIA, FLIBUSTA_BASE_URL
from utils import split_query_into_words, extract_criteria, get_cover_url

Book = namedtuple('Book', ['FileName', 'Title', 'SearchTitle', 'SearchLang', 'Author', 'LastName', 'FirstName', 'MiddleName', 'Genre', 'GenreParent', 'Folder', 'Ext', 'BookSize', 'SearchYear', 'LibRate', 'UpdateDate'])
UserSettings = namedtuple('UserSettings',['User_ID', 'MaxBooks', 'Lang', 'DateSortOrder', 'BookFormat', 'LastNewsDate', 'IsBlocked'])

# SQL-запросы
SQL_QUERY_BOOKS = """
    select * from (
    SELECT 
        b.Title,
        upper(b.Lang) as SearchLang,
        b.FileSize as BookSize,
        round(coalesce(r.LibRate,0)) as LibRate, 
        case 
          when b.FileSize <= 800 * 1024 then 'less800'
          when b.FileSize > 800 * 1024 then 'more800'
          end as BookSizeCat,        
        '' as Folder,
        b.bookid as FileName,
        b.FileType as Ext,
        upper(b.Title) as SearchTitle,
        date(b.Time) as UpdateDate,
        upper(concat(coalesce(an.LastName,''), ' ', coalesce(an.FirstName,''), ' ', coalesce(an.MiddleName,''))) AS Author,
        an.LastName,
        an.FirstName,
        an.MiddleName,
        sn.SeqName as SeriesTitle, 
        upper(sn.SeqName) as SearchSeriesTitle,
        gl.GenreDesc AS Genre,
        upper(gl.GenreDesc) as GenreUpper,
        gl.GenreMeta AS GenreParent,
        b.Year as SearchYear, 
    --    upper(bm.City) as SearchCity, 
    --    upper(bm.Publisher) as SearchPublisher,
        upper(regexp_replace(concat(' ', b.Title, ' ', coalesce(an.LastName,''), ' ', coalesce(an.FirstName,''), ' ', coalesce(an.MiddleName,''), ' ', coalesce(sn.SeqName,''), ' ', coalesce(gl.GenreDesc,''), ' ', b.Lang, ' ')  COLLATE utf8mb3_bin,'[[:punct:]]',' ')) AS FullSearch,
        b.Pages,
        an.AvtorID as AuthorID
    FROM libbook b
    LEFT JOIN libavtor a ON a.BookID = b.BookID
    LEFT JOIN libavtorname an ON a.AvtorID = an.AvtorID
    LEFT JOIN libseq s ON s.BookID = b.BookID
    left join libseqname sn on s.SeqID = sn.SeqID
    LEFT JOIN libgenre g ON g.BookID = b.BookID
    left JOIN libgenrelist gl ON gl.GenreID = g.GenreID
    -- left outer JOIN libbook_meta bm ON bm.BookID = b.BookID 
    left outer join ( 
      select 
        r.BookId, 
        avg(cast(r.Rate as signed)) as Librate
      from librate r 
      group by r.BookId 
      ) r on r.BookId = b.BookId
    where b.Deleted = '0' ) as subq
"""

SQL_QUERY_PARENT_GENRES_COUNT = """
	select coalesce(GenreMeta,'Неотсортированное'), count(b.BookId)
      from libbook b
        left outer join libgenre g on b.BookId = g.BookId 
        left outer join libgenrelist gl on g.GenreId = gl.GenreId 
    where b.Deleted = '0'
    group by coalesce(GenreMeta, 'Неотсортированное') 
    order by 1
"""

SQL_QUERY_CHILDREN_GENRES_COUNT = """
	select gl.GenreDesc, count(g.BookId)
      from libbook b
	    left outer join libgenre g on b.BookId = g.BookId 
        left outer join libgenrelist gl on g.GenreId = gl.GenreId 
    Where 
      b.Deleted = '0' and
      gl.GenreMeta = %s
    group by gl.GenreDesc 
    order by 1	
"""

SQL_QUERY_LANGS = """
    SELECT Lang, COUNT(Lang) AS count
    FROM libbook b
    where b.Deleted = '0'
    GROUP BY Lang
    ORDER BY count DESC
"""

SQL_QUERY_USER_SETTINGS_GET = """
    SELECT * FROM UserSettings WHERE user_id = ?
"""

SQL_QUERY_USER_SETTINGS_INS_DEFAULT = """
    INSERT INTO UserSettings (user_id) VALUES (?)
"""

SQL_QUERY_USER_SETTINGS_UPD = """
    UPDATE UserSettings SET ? = ? WHERE USER_ID = ?
"""

class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self._conn = None  # Защищённая переменная для хранения соединения
        # Создаем директорию для БД если не существует
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def connect(self):
        """Устанавливает соединение с базой данных и инициализирует её если нужно"""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            # Инициализируем БД при первом подключении
            self._initialize_database()
        return self._conn

    def _initialize_database(self):
        """Базовый метод инициализации (переопределяется в дочерних классах)"""
        pass

    def close(self):
        """
        Закрывает соединение с базой данных, если оно установлено.
        """
        if self._conn is not None:
            self._conn.close()
            self._conn = None

# Класс для работы с БД настроек бота
class DatabaseLogs(Database):
    def __init__(self, db_path = FLIBUSTA_DB_LOGS_PATH):
        super().__init__(db_path)

    def _initialize_database(self):
        """Инициализирует БД логов при первом подключении"""
        with self.connect() as conn:
            cursor = conn.cursor()

            # Создаем таблицу если не существует
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS UserLog (
                    Timestamp VARCHAR(27) NOT NULL,
                    UserID INTEGER NOT NULL,
                    UserName VARCHAR(50),
                    Action VARCHAR(50) COLLATE NOCASE,
                    Detail VARCHAR(255) COLLATE NOCASE,
                    PRIMARY KEY(Timestamp, UserID)
                );
            """)

            # Создаем индекс если не существует
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS IXUserLog_UserID_Timestamp 
                ON UserLog (UserID, Timestamp);
            """)

            conn.commit()

    def write_user_log(self, timestamp, user_id, user_name, action, detail = ''):
        with self.connect() as conn:
            cursor = conn.cursor()

            cursor.execute(f"""
                INSERT INTO UserLog (Timestamp, UserID, UserName, Action, Detail) 
                VALUES (?, ?, ?, ?, ?)
            """, (timestamp, user_id, user_name, action, detail))

            conn.commit()


    def get_user_stats_period(self, days):
        """Возвращает статистику пользователей за указанный период в днях"""
        with self.connect() as conn:
            cursor = conn.cursor()

            # Новые пользователи за период
            cursor.execute("""
                SELECT COUNT(*) AS NewUsers
                FROM (
                    SELECT UserID, MIN(Timestamp) AS FirstSeen
                    FROM UserLog
                    GROUP BY UserID
                    HAVING date(FirstSeen) >= date('now', ?)
                )
            """, (f'-{days} days',))
            new_users = cursor.fetchone()[0]

            # Активные пользователи за период
            cursor.execute("""
                SELECT COUNT(DISTINCT UserID) AS ActiveUsers
                FROM UserLog
                WHERE date(Timestamp) >= date('now', ?)
            """, (f'-{days} days',))
            active_users = cursor.fetchone()[0]

            # Количество поисков и скачиваний за период
            cursor.execute("""
                SELECT 
                    SUM(CASE WHEN Action LIKE 'searched%' THEN 1 ELSE 0 END) AS TotalSearches,
                    SUM(CASE WHEN Action = 'send file' THEN 1 ELSE 0 END) AS TotalDownloads
                FROM UserLog
                WHERE date(Timestamp) >= date('now', ?)
            """, (f'-{days} days',))
            searches, downloads = cursor.fetchone()

            return {
                'new_users': new_users,
                'active_users': active_users,
                'searches': searches or 0,
                'downloads': downloads or 0
            }


    def get_user_stats_total(self):
        """Возвращает общую статистику пользователей за всё время"""
        with self.connect() as conn:
            cursor = conn.cursor()

            # Общее количество пользователей
            cursor.execute("SELECT COUNT(DISTINCT UserID) AS TotalUniqueUsers FROM UserLog")
            total_users = cursor.fetchone()[0]

            # Активные пользователи всего (кто был активен хотя бы раз)
            cursor.execute("SELECT COUNT(DISTINCT UserID) AS ActiveUsersTotal FROM UserLog")
            active_users_total = cursor.fetchone()[0]

            # Количество поисков и скачиваний всего
            cursor.execute("""
                SELECT 
                    SUM(CASE WHEN Action LIKE 'searched%' THEN 1 ELSE 0 END) AS TotalSearches,
                    SUM(CASE WHEN Action = 'send file' THEN 1 ELSE 0 END) AS TotalDownloads
                FROM UserLog
            """)
            searches_total, downloads_total = cursor.fetchone()

            return {
                'total_users': total_users,
                'active_users_total': active_users_total,
                'searches_total': searches_total or 0,
                'downloads_total': downloads_total or 0
            }


    def get_user_stats_summary(self):
        """Возвращает общую статистику пользователей"""
        stats_week = self.get_user_stats_period(7)
        stats_month = self.get_user_stats_period(30)
        stats_total = self.get_user_stats_total()

        return {
            'total_users': stats_total['total_users'],
            'new_users_week': stats_week['new_users'],
            'active_users_week': stats_week['active_users'],
            'searches_week': stats_week['searches'],
            'downloads_week': stats_week['downloads'],
            'new_users_month': stats_month['new_users'],
            'active_users_month': stats_month['active_users'],
            'searches_month': stats_month['searches'],
            'downloads_month': stats_month['downloads'],
            'active_users_total': stats_total['active_users_total'],
            'searches_total': stats_total['searches_total'],
            'downloads_total': stats_total['downloads_total']
        }


    def get_users_list(self, limit=50, offset=0):
        """Возвращает список пользователей с основной информацией"""
        with self.connect() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    UserID,
                    MIN(UserName) AS UserName,
                    MAX(datetime(Timestamp)) AS LastSeen,
                    MIN(datetime(Timestamp)) AS FirstSeen,
                    SUM(CASE WHEN Action LIKE 'searched for%' THEN 1 ELSE 0 END) AS TotalSearches,
                    SUM(CASE WHEN Action = 'send file' THEN 1 ELSE 0 END) AS TotalDownloads
                FROM UserLog
                GROUP BY UserID
                ORDER BY LastSeen DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))

            users = []
            for row in cursor.fetchall():
                users.append({
                    'user_id': row[0],
                    'username': row[1] or 'Без имени',
                    'last_seen': row[2],
                    'first_seen': row[3],
                    'total_searches': row[4] or 0,
                    'total_downloads': row[5] or 0
                })

            return users

    def get_user_activity(self, user_id, limit=50):
        """Возвращает историю действий пользователя"""
        with self.connect() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT datetime(Timestamp), Action, Detail
                FROM UserLog
                WHERE UserID = ?
                ORDER BY Timestamp DESC
                LIMIT ?
            """, (user_id, limit))

            activities = []
            for row in cursor.fetchall():
                activities.append({
                    'timestamp': row[0],
                    'action': row[1],
                    'detail': row[2] or ''
                })

            return activities

    def get_recent_searches(self, limit=20):
        """Возвращает последние поисковые запросы"""
        with self.connect() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT Detail AS SearchQuery, datetime(Timestamp), UserName
                FROM UserLog
                WHERE Action LIKE 'searched for%'
                ORDER BY Timestamp DESC
                LIMIT ?
            """, (limit,))

            return cursor.fetchall()

    def get_recent_downloads(self, limit=20):
        """Возвращает последние скачивания"""
        with self.connect() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT Detail AS filename, datetime(Timestamp), UserName
                FROM UserLog
                WHERE Action = 'send file'
                ORDER BY Timestamp DESC
                LIMIT ?
            """, (limit,))

            return cursor.fetchall()

    def get_top_downloads(self, limit=20):
        """Возвращает топ скачанных книг"""
        with self.connect() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT Detail AS FileName, COUNT(*) AS DownloadCount
                FROM UserLog
                WHERE Action = 'send file'
                GROUP BY Detail
                ORDER BY DownloadCount DESC
                LIMIT ?
            """, (limit,))

            return cursor.fetchall()

    def get_daily_user_stats(self, days=7):
        """Возвращает статистику пользователей по дням"""
        with self.connect() as conn:
            cursor = conn.cursor()

            # Статистика новых пользователей по дням
            cursor.execute("""
                SELECT 
                    date(FirstSeen) as day,
                    COUNT(*) as new_users
                FROM (
                    SELECT UserID, MIN(Timestamp) AS FirstSeen
                    FROM UserLog
                    GROUP BY UserID
                    HAVING date(FirstSeen) >= date('now', ?)
                )
                GROUP BY date(FirstSeen)
                ORDER BY day DESC
            """, (f'-{days} days',))

            new_users_by_day = {}
            for row in cursor.fetchall():
                new_users_by_day[row[0]] = row[1]

            # Статистика активных пользователей по дням
            cursor.execute("""
                SELECT 
                    date(Timestamp) as day,
                    COUNT(DISTINCT UserID) as active_users
                FROM UserLog
                WHERE date(Timestamp) >= date('now', ?)
                GROUP BY date(Timestamp)
                ORDER BY day DESC
            """, (f'-{days} days',))

            active_users_by_day = {}
            for row in cursor.fetchall():
                active_users_by_day[row[0]] = row[1]

            # Статистика поисков и скачиваний по дням
            cursor.execute("""
                SELECT 
                    date(Timestamp) as day,
                    SUM(CASE WHEN Action LIKE 'searched for%' THEN 1 ELSE 0 END) as searches,
                    SUM(CASE WHEN Action = 'send file' THEN 1 ELSE 0 END) as downloads
                FROM UserLog
                WHERE date(Timestamp) >= date('now', ?)
                GROUP BY date(Timestamp)
                ORDER BY day DESC
            """, (f'-{days} days',))

            searches_by_day = {}
            downloads_by_day = {}
            for row in cursor.fetchall():
                searches_by_day[row[0]] = row[1] or 0
                downloads_by_day[row[0]] = row[2] or 0

            # Формируем полный список дней
            import datetime
            dates = []
            for i in range(days):
                date = (datetime.datetime.now() - datetime.timedelta(days=i)).strftime('%Y-%m-%d')
                dates.append(date)

            # Заполняем данные для всех дней (даже если их нет в БД)
            result = {
                'dates': dates,
                'new_users': [new_users_by_day.get(date, 0) for date in dates],
                'active_users': [active_users_by_day.get(date, 0) for date in dates],
                'searches': [searches_by_day.get(date, 0) for date in dates],
                'downloads': [downloads_by_day.get(date, 0) for date in dates]
            }

            return result

    def get_top_searches(self, limit=20):
        """Возвращает топ поисковых запросов"""
        with self.connect() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT 
                    Detail AS SearchQuery, 
                    COUNT(*) AS SearchCount,
                    COUNT(DISTINCT UserID) AS UniqueUsers
                FROM UserLog
                WHERE Action LIKE 'searched for%' AND Detail NOT LIKE '%count:0'
                GROUP BY Detail
                ORDER BY SearchCount DESC
                LIMIT ?
            """, (limit,))

            top_searches = []
            for row in cursor.fetchall():
                top_searches.append({
                    'query': row[0],
                    'count': row[1],
                    'unique_users': row[2]
                })

            return top_searches

    def get_user_by_id(self, user_id):
        """Возвращает информацию о конкретном пользователе по ID"""
        with self.connect() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    UserID,
                    MIN(UserName) AS UserName,
                    MAX(datetime(Timestamp)) AS LastSeen,
                    MIN(datetime(Timestamp)) AS FirstSeen,
                    SUM(CASE WHEN Action LIKE 'searched for%' THEN 1 ELSE 0 END) AS TotalSearches,
                    SUM(CASE WHEN Action = 'send file' THEN 1 ELSE 0 END) AS TotalDownloads
                FROM UserLog
                WHERE UserID = ?
                GROUP BY UserID
            """, (user_id,))

            row = cursor.fetchone()
            if row:
                return {
                    'user_id': row[0],
                    'username': row[1] or 'Без имени',
                    'last_seen': row[2],
                    'first_seen': row[3],
                    'total_searches': row[4] or 0,
                    'total_downloads': row[5] or 0
                }
            return None


# Класс для работы с БД настроек бота
class DatabaseSettings(Database):
    def __init__(self, db_path = FLIBUSTA_DB_SETTINGS_PATH):
        super().__init__(db_path)

    def _initialize_database(self):
        """Инициализирует БД настроек при первом подключении"""
        with self.connect() as conn:
            cursor = conn.cursor()

            # Создаем таблицу если не существует
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS UserSettings (
                    User_ID INTEGER NOT NULL UNIQUE,
                    MaxBooks INTEGER NOT NULL DEFAULT 20,
                    Lang VARCHAR(2) DEFAULT '',
                    DateSortOrder VARCHAR(10) DEFAULT 'DESC',
                    BookFormat VARCHAR(5) DEFAULT 'fb2',
                    LastNewsDate VARCHAR(10) DEFAULT '2000-01-01',
                    IsBlocked BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY(User_ID)
                );
            """)

            # Создаем индекс если не существует
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS IXUserSettings_User_ID 
                ON UserSettings (User_ID);
            """)

            conn.commit()

    def get_user_settings(self,user_id):
        """
        Получает настройки пользователя из базы данных.
        """
        fields = UserSettings._fields
        processed_fields = [field for field in fields]
        select_fields = ', '.join(processed_fields)

        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT {select_fields} FROM UserSettings WHERE user_id = ?", (user_id,))
            settings = cursor.fetchone()
            # Если настроек нет, добавляем значения по умолчанию
            if not settings:
                cursor.execute("INSERT INTO UserSettings (user_id) VALUES (?)", (user_id,))
                conn.commit()
                cursor.execute(f"SELECT {select_fields} FROM UserSettings WHERE user_id = ?", (user_id,))
                settings = cursor.fetchone()
        return UserSettings(*settings)

    def update_user_settings(self, user_id, **kwargs):
        """
        Обновляет настройки пользователя в базе данных.
        """
        with self.connect() as conn:
            cursor = conn.cursor()

            # Формируем SQL-запрос для обновления настроек
            set_clause = ", ".join([f"{key} = ?" for key in kwargs])
            values = list(kwargs.values()) + [user_id]

            cursor.execute(f"""
                UPDATE UserSettings 
                SET {set_clause}
                WHERE user_id = ?
            """, values)

            conn.commit()

    def get_user_stats(self):
        """Возвращает статистику пользователей"""
        with self.connect() as conn:
            cursor = conn.cursor()

            # Общая статистика
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_users,
                    SUM(CASE WHEN IsBlocked THEN 1 ELSE 0 END) as blocked_users,
                    SUM(CASE WHEN LastNewsDate > '2000-01-01' THEN 1 ELSE 0 END) as active_users
                FROM UserSettings
            """)
            stats = cursor.fetchone()

            return {
                'total_users': stats[0],
                'blocked_users': stats[1],
                'active_users': stats[2]
            }


# Класс для работы с БД библиотеки
class DatabaseBooks():
    _class_cached_langs = None
    _class_cached_parent_genres = None
    _class_cached_genres = {}  # Словарь для кеширования жанров по родительским категориям

    def __init__(self, db_config):
        self.db_config = db_config
        self._connection = None
        # self._cached_langs = None
        # self._cached_parent_genres = None
        # self._cached_genres = {}  # Словарь для кеширования жанров по родительским категориям

    @contextmanager
    def connect(self):
        """Устанавливает соединение с MariaDB"""
        conn = mysql.connector.connect(**self.db_config)
        try:
            yield conn
        finally:
            conn.close()


    def get_library_stats(self):
        """Возвращает статистику библиотеки"""
        try:
            with self.connect() as conn:
                cursor = conn.cursor()

                # Статистика книг
                cursor.execute("""
                    SELECT 
                        MAX(date(time)) as max_update_date,
                        COUNT(*) as books_cnt,
                        MAX(bookid) as max_filename
                    FROM libbook b
                    where b.Deleted = '0'
                """)
                books_stats = cursor.fetchone()

                # Количество авторов
                cursor.execute("SELECT COUNT(*) FROM libavtorname")
                authors_cnt = cursor.fetchone()[0]

                # Количество жанров
                cursor.execute("SELECT COUNT(*) FROM libgenrelist")
                genres_cnt = cursor.fetchone()[0]

                # Количество серий
                cursor.execute("SELECT COUNT(*) FROM libseqname")
                series_cnt = cursor.fetchone()[0]

                # Количество языков
                cursor.execute("SELECT COUNT(DISTINCT Lang) FROM libbook WHERE Deleted = '0'")
                langs_cnt = cursor.fetchone()[0]

                return {
                    'last_update': books_stats[0],
                    'books_count': books_stats[1],
                    'max_filename': books_stats[2],
                    'authors_count': authors_cnt,
                    'genres_count': genres_cnt,
                    'series_count': series_cnt,
                    'languages_count': langs_cnt
                }
        except Exception as e:
            print(f"Error getting library stats: {e}")
            return {
                'last_update': None,
                'books_count': 0,
                'max_filename': 'N/A',
                'authors_count': 0,
                'genres_count': 0,
                'series_count': 0,
                'languages_count': 0
            }


    def get_parent_genres_with_counts(self):
        """Получает родительские жанры с кешированием"""
        if DatabaseBooks._class_cached_parent_genres is None:
            with self.connect() as conn:
                cursor = conn.cursor(buffered=True)
                cursor.execute(SQL_QUERY_PARENT_GENRES_COUNT)
                DatabaseBooks._class_cached_parent_genres = cursor.fetchall()
        return DatabaseBooks._class_cached_parent_genres


    def get_genres_with_counts(self, parent_genre):
        if parent_genre not in DatabaseBooks._class_cached_genres:
            with self.connect() as conn:
                cursor = conn.cursor(buffered=True)
                cursor.execute(SQL_QUERY_CHILDREN_GENRES_COUNT, (parent_genre,))
                results = cursor.fetchall()
                DatabaseBooks._class_cached_genres[parent_genre] = [(genre[0].strip(), genre[1]) for genre in results if genre[0].strip()]
        return DatabaseBooks._class_cached_genres[parent_genre]


    def get_langs(self):
        """Получает языки с кешированием"""
#        with self.connect() as conn:
#            cursor = conn.cursor()
#            cursor.execute(SQL_QUERY_LANGS)
#            results = cursor.fetchall()
#        return results
        if DatabaseBooks._class_cached_langs is None:
            with self.connect() as conn:
                cursor = conn.cursor(buffered=True)
                cursor.execute(SQL_QUERY_LANGS)
                DatabaseBooks._class_cached_langs = cursor.fetchall()
        return DatabaseBooks._class_cached_langs


    def search_books(self, query, max_books, lang, sort_order, size_limit, rating_filter=None):
        # Разбиваем запрос на критерии и их значения
        criteries = extract_criteria(query)
        if criteries:
            # Если критерии заданы, формируем условие поиска книг по этим критериям
            sql_where, params = self.build_sql_where_by_criteria(criteries, lang, size_limit, rating_filter)
        else:
            # Если критерии не заданы, формируем условие поиска книг по словам в запросе
            words = split_query_into_words(query)
            sql_where, params = self.build_sql_where(words, lang, size_limit, rating_filter)

        # Строим запросы для поиска книг и подсчёта количества найденных книг
        sql_query, sql_query_cnt = self.build_sql_queries(sql_where, max_books, sort_order)

        # #DEBUG
        # print(f"DEBUG: sql_query = {sql_query}")
        # print(f"DEBUG: params = {params}")

        # выполняем запросы поиска книг и подсчёта количества найденных книг
        with self.connect() as conn:
            # conn.create_function("REMOVE_PUNCTUATION", 1, remove_punctuation)
            cursor = conn.cursor(buffered=True)
            cursor.execute(sql_query, params)
            books = [Book(*row) for row in cursor.fetchall()]
            cursor.execute(sql_query_cnt, params)
            count = cursor.fetchone()[0]

        return books, count


    async def get_book_info(self, book_id):
        """Получает основную информацию о книге"""
        with self.connect() as conn:
            cursor = conn.cursor(buffered=True)
            cursor.execute("""
                SELECT b.Title, b.Year, sn.SeqName,
                       GROUP_CONCAT(DISTINCT gl.GenreDesc SEPARATOR ', ') as Genres,
                       GROUP_CONCAT(DISTINCT CONCAT(an.LastName, ' ', an.FirstName) SEPARATOR ', ') as Authors,
                       bp.File, b.FileSize, b.Pages, b.Lang, r.LibRate
                FROM libbook b
                LEFT JOIN libavtor a ON a.BookID = b.BookID
                LEFT JOIN libavtorname an ON a.AvtorID = an.AvtorID
                LEFT JOIN libseq s ON s.BookID = b.BookID
                LEFT JOIN libseqname sn ON s.SeqID = sn.SeqID
                LEFT JOIN libgenre g ON g.BookID = b.BookID
                LEFT JOIN libgenrelist gl ON g.GenreID = gl.GenreID
                LEFT JOIN libbpics bp ON b.BookID = bp.BookID
                left outer join ( 
                    select 
                        r.BookId, 
                        avg(cast(r.Rate as signed)) as Librate
                    from librate r 
                    group by r.BookId 
                    ) r on r.BookId = b.BookId
                WHERE b.BookID = %s
                GROUP BY b.Title, b.Year, sn.SeqName, bp.File, b.FileSize, b.Pages, b.Lang
            """, (book_id,))
            result = cursor.fetchone()
            cover_url = f"{FLIBUSTA_BASE_URL}/ib/{result[5]}" if result[5] else None
            # print(f"DEBUG: cover_url = {cover_url}")
            # Получение ссылки на обложку со страницы книги, если нет в БД
            if not cover_url:
                cover_url = await get_cover_url(book_id)
                # print(f"DEBUG: cover_url = {cover_url}")

            return {
                'title': result[0],
                'year': result[1],
                'series': result[2],
                'genre': result[3],
                'authors': result[4],
                'cover_url': cover_url,
                'size': result[6],
                'pages': result[7],
                'lang': result[8],
                'rate': result[9],
            } if result else None

    async def get_book_details(self, book_id):
        """Получает детальную информацию о книге с обложкой и аннотацией"""
        with self.connect() as conn:
            cursor = conn.cursor(buffered=True)

            # # Получаем обложку
            # cursor.execute("SELECT File FROM libbpics WHERE BookID = %s", (book_id,))
            # cover_result = cursor.fetchone()
            # cover_url = f"{FLIBUSTA_BASE_URL}/ib/{cover_result[0]}" if cover_result else None

            # Получаем аннотацию
            cursor.execute("SELECT title, Body FROM libbannotations WHERE BookID = %s", (book_id,))
            annotation_result = cursor.fetchone()

            return {
                # 'cover_url': cover_url,
                'title': annotation_result[0],
                'annotation': annotation_result[1]
            } if annotation_result else None


    def search_series(self, query, max_books, lang, size_limit, rating_filter=None):
        """Ищет серии по запросу"""
        # Разбиваем запрос на критерии
        criteries = extract_criteria(query)

        if criteries:
            sql_where, params = self.build_sql_where_by_criteria(criteries, lang, size_limit, rating_filter)
        else:
            words = split_query_into_words(query)
            sql_where, params = self.build_sql_where(words, lang, size_limit, rating_filter)

        # Модифицируем запрос для поиска серий
        sql_query = f"""
        SELECT 
            SeriesTitle, 
            SearchSeriesTitle,
            COUNT(DISTINCT FileName) as book_count
        FROM ({SQL_QUERY_BOOKS} {sql_where}) as subquery
        WHERE SeriesTitle IS NOT NULL
        GROUP BY SeriesTitle, SearchSeriesTitle
        ORDER BY book_count DESC, SeriesTitle
        -- LIMIT {max_books}
        """

        sql_query_cnt = f"SELECT COUNT(*) FROM ({sql_query}) as subquery2"

        # #debug
        # print(sql_query)
        # print(params)

        with self.connect() as conn:
            # conn.create_function("REMOVE_PUNCTUATION", 1, remove_punctuation)
            cursor = conn.cursor(buffered=True)
            cursor.execute(sql_query, params)
            series = cursor.fetchall()
            cursor.execute(sql_query_cnt, params)
            count = cursor.fetchone()[0]

        return series, count


    async def get_authors_id(self, book_id: int) -> List:
        """Получает ID авторов книги"""
        with self.connect() as conn:
            cursor = conn.cursor(buffered=True)

            # Получаем id всех авторов книги
            cursor.execute("""
                SELECT DISTINCT a.AvtorID 
                FROM libavtor a 
                WHERE a.BookID = %s
            """, (book_id,))
            author_result = cursor.fetchall()

            if not author_result:
                return None
            else:
                return [author_id[0] for author_id in author_result]


    async def get_author_info(self, author_id: int) -> Dict:
        """Получает информацию об авторе книги"""
        with self.connect() as conn:
            cursor = conn.cursor(buffered=True)

            # Получаем первого автора книги
            cursor.execute("""
                SELECT an.AvtorID, an.LastName, an.FirstName, an.MiddleName 
                -- FROM libavtor a 
                -- JOIN libavtorname an ON a.AvtorID = an.AvtorID 
                FROM libavtorname an
                WHERE an.AvtorID = %s
                LIMIT 1
            """, (author_id,))
            author_result = cursor.fetchone()

            if not author_result:
                return None

            # Получаем фото автора
            cursor.execute("SELECT File FROM libapics WHERE AvtorID = %s", (author_id,))
            photo_result = cursor.fetchone()
            photo_url = f"{FLIBUSTA_BASE_URL}/ia/{photo_result[0]}" if photo_result else None

            # Получаем аннотацию автора
            cursor.execute("SELECT title, Body FROM libaannotations WHERE AvtorID = %s", (author_id,))
            annotation_result = cursor.fetchone()

            return {
                'name': f"{author_result[1]} {author_result[2]} {author_result[3]}",
                'photo_url': photo_url,
                'title': annotation_result[0],
                'biography': annotation_result[1]
            } if annotation_result else None


    async def get_book_reviews(self, book_id):
        """Получает отзывы о книге"""
        with self.connect() as conn:
            cursor = conn.cursor(buffered=True)
            cursor.execute("""
                SELECT Name, Time, Text 
                FROM libreviews 
                WHERE BookID = %s 
                ORDER BY Time DESC
            """, (book_id,))
            return cursor.fetchall()


    def search_authors(self, query, max_books, lang, size_limit, rating_filter=None):
        """Ищет авторов по запросу"""
        # Разбиваем запрос на критерии
        criteries = extract_criteria(query)

        if criteries:
            sql_where, params = self.build_sql_where_by_criteria(criteries, lang, size_limit, rating_filter)
        else:
            words = split_query_into_words(query)
            sql_where, params = self.build_sql_where(words, lang, size_limit, rating_filter)

        # Модифицируем запрос для поиска авторов
        sql_query = f"""
        SELECT 
            CONCAT(COALESCE(LastName, ''), ' ', COALESCE(FirstName, ''), ' ', COALESCE(MiddleName, '')) as AuthorName,
            UPPER(CONCAT(COALESCE(LastName, ''), ' ', COALESCE(FirstName, ''), ' ', COALESCE(MiddleName, ''))) as SearchAuthorName,
            COUNT(DISTINCT FileName) as book_count,
            AuthorID
        FROM ({SQL_QUERY_BOOKS} {sql_where}) as subquery
        WHERE LastName <> '' OR FirstName <> '' OR MiddleName <> ''
        GROUP BY AuthorName, SearchAuthorName, AuthorID
        ORDER BY book_count DESC, AuthorName
        -- LIMIT {max_books}
        """

        sql_query_cnt = f"SELECT COUNT(*) FROM ({sql_query}) as subquery2"

        with self.connect() as conn:
            cursor = conn.cursor(buffered=True)
            cursor.execute(sql_query, params)
            authors = cursor.fetchall()
            cursor.execute(sql_query_cnt, params)
            count = cursor.fetchone()[0]

        return authors, count


    @staticmethod
    def make_condition(field, source_word, operator, whole_word = True):
        """
        Формируем строку условия where по отдельному полю с учётом заданного оператора и индикатора целого слова
        :param field: поле для поиска в БД
        :param source_word: исходное слово поиска
        :param operator: оператор поиска
        :param whole_word: индикатор поиска целого слова
        :return: отдельная строка условия where для заданного поля
        """
        condition = ''
        value = ''
        if whole_word:
            # если ищем целое отдельное слово, окружаем его пробелами
            word = f" {source_word.upper()} "
        else:
            word = source_word.upper()

        if operator == 'LIKE':
            #condition = f"{field} LIKE '%{word}%'"  # COLLATE MHL_SYSTEM_NOCASE")
            condition = f"{field} LIKE %s"  # COLLATE MHL_SYSTEM_NOCASE")
            value = f'%{word}%'
        elif operator == '<>':
            #condition = f"{field} NOT LIKE '%{word}%'"  # COLLATE MHL_SYSTEM_NOCASE")
            condition = f"{field} NOT LIKE %s"  # COLLATE MHL_SYSTEM_NOCASE")
            value = '%{word}%'
        elif operator == '=':
            #condition = f"{field} LIKE '{word}'"  # COLLATE MHL_SYSTEM_NOCASE")
            condition = f"{field} = %s"  # COLLATE MHL_SYSTEM_NOCASE") #LIKE
            value = f'{word}'
        elif operator == '<=':
            # condition = f"{field} LIKE '{word}'"  # COLLATE MHL_SYSTEM_NOCASE")
            condition = f"{field} <= %s"  # COLLATE MHL_SYSTEM_NOCASE") #LIKE
            value = f'{word}'
        elif operator == '>=':
            # condition = f"{field} LIKE '{word}'"  # COLLATE MHL_SYSTEM_NOCASE")
            condition = f"{field} >= %s"  # COLLATE MHL_SYSTEM_NOCASE") #LIKE
            value = f'{word}'
        elif operator == 'NOT LIKE':
            #condition = f"{field} NOT LIKE '%{word}%'"  # COLLATE MHL_SYSTEM_NOCASE")
            condition = f"{field} NOT LIKE %s"  # COLLATE MHL_SYSTEM_NOCASE")
            value = f'%{word}%'

        return  condition, value


    @staticmethod
    def build_sql_where(words, lang, size_limit, rating_filter=None):
        """
        Создает SQL-условие WHERE на основе списка слов и их операторов.
        """
        conditions = []
        params = []
        for word, operator in words:
            condition, param = DatabaseBooks.make_condition("FullSearch", word, operator)
            conditions.append(condition)
            params.append(param)

        # Добавляем условие по языку, если задан в настройках пользователя
        if lang and conditions:
            conditions.append(f"SearchLang LIKE '{lang.upper()}'")

        # Добавляем ограничение по размеру книг, если задан в настройках пользователя
        if size_limit:
            conditions.append(f"BookSizeCat = '{size_limit}'")

        # ДОБАВЛЯЕМ ФИЛЬТРАЦИЮ ПО РЕЙТИНГУ
        if rating_filter and rating_filter != '':
            rating_values = [r.strip() for r in rating_filter.split(',') if r.strip()]
            if rating_values:
                rating_condition = f"LibRate IN ({', '.join(['%s'] * len(rating_values))})"
                conditions.append(rating_condition)
                params.extend(rating_values)

        # в соновном sql вконце уже есть where, поэтому заменяем его на and
        sql_where = "WHERE " + " AND ".join(conditions) if conditions else "WHERE 1=2"
        return sql_where, params


    @staticmethod
    def build_sql_queries(sql_where, max_books, sort_order):
        fields = Book._fields
        processed_fields = [fields[0]] + [f"max({field})" for field in fields[1:]]
        select_fields = ', '.join(processed_fields)

        sql_query = f"""
            SELECT {select_fields} 
            FROM ( {SQL_QUERY_BOOKS} {sql_where} ) as subquery
            GROUP BY {fields[0]}
            ORDER BY {fields[-1]} {sort_order}
            -- LIMIT {max_books}
        """
        sql_query_cnt = f"""
            SELECT COUNT(*) 
            FROM (SELECT {select_fields} FROM ({SQL_QUERY_BOOKS} {sql_where}) as subquery1 GROUP BY {fields[0]}) as subquery2
        """
        return sql_query, sql_query_cnt


    @staticmethod
    def build_sql_where_by_criteria(criteria_tuples, lang, size_limit, rating_filter=None):
        # Базовая часть SQL-запроса
        # в соновном sql вконце уже есть where, поэтому заменяем его на and
        sql_where = "WHERE "

        # Список для хранения условий
        conditions = []
        params = []
        # Словарь для хранения OR условий
        or_groups = {}

        column_mapping = SEARCH_CRITERIA

        # Формируем условия для каждого критерия
        for criterion, value, operator, combiner in criteria_tuples:
            # Преобразуем критерий в название столбца
            column = column_mapping.get(criterion.lower())
            if column:
                # Преобразуем значение в верхний регистр и добавляем условие LIKE
                #value_processed = value.upper()
                #values = split_query_into_words(value_processed)
                #condition = f"{column} LIKE '%{value_processed}%'"
                if combiner == 'OR':
                    key = f"{column}"
                    if key not in or_groups:
                        or_groups[key] = []
                    or_groups[key].append((column, operator, value))
                else:
                    condition, param = DatabaseBooks.make_condition(column, value.upper(), operator, False)
                    conditions.append(condition)
                    params.append(param)

        # Добавляем OR-условия
        for key, or_conditions in or_groups.items():
            or_parts = []
            for column, operator, value in or_conditions:
                condition, param = DatabaseBooks.make_condition(column, value.upper(), operator, False)
                or_parts.append(condition)
                params.append(param)
            conditions.append(f"({' OR '.join(or_parts)})")

        # Добавляем условие по языку, если задан в настройках пользователя
        if lang and conditions:
            conditions.append(f"SearchLang LIKE '{lang.upper()}'")

        # Добавляем ограничение по размеру книг, если задан в настройках пользователя
        if size_limit:
            conditions.append(f"BookSizeCat = '{size_limit}'")

        # ДОБАВЛЯЕМ ФИЛЬТРАЦИЮ ПО РЕЙТИНГУ
        if rating_filter and rating_filter != '':
            rating_values = [r.strip() for r in rating_filter.split(',') if r.strip()]
            if rating_values:
                rating_condition = f"LibRate IN ({', '.join(['%s'] * len(rating_values))})"
                conditions.append(rating_condition)
                params.extend(rating_values)

        # Объединяем условия через AND
        if conditions:
            sql_where += " AND ".join(conditions)
        else:
            # Если условий нет, возвращаем запрос false
            sql_where += "1=2"

        return sql_where, params



