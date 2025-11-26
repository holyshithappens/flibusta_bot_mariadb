import os
import sqlite3
from collections import namedtuple
from typing import Dict, List, Any, Coroutine

import mysql.connector
from contextlib import contextmanager

from flibusta_client import FlibustaClient, flibusta_client
# from constants import SETTING_SORT_ORDER_DESC
from constants import FLIBUSTA_DB_SETTINGS_PATH, FLIBUSTA_DB_LOGS_PATH, MAX_BOOKS_SEARCH, \
    SETTING_SEARCH_AREA_B, SETTING_SEARCH_AREA_BA, SETTING_SEARCH_AREA_AA

Book = namedtuple('Book',
                  ['FileName', 'Title', 'LastName', 'FirstName', 'MiddleName', 'Genre', 'BookSize',
                   'SearchYear', 'LibRate', 'SeriesTitle', 'Relevance'])
UserSettingsType = namedtuple('UserSettingsType',
                              ['User_ID', 'MaxBooks', 'Lang',
                               # 'DateSortOrder',
                               'BookFormat', 'LastNewsDate', 'IsBlocked', 'BookSize', 'SearchType', 'Rating', 'SearchArea'])

# SQL-запросы
# Базовые поля для SELECT
BASE_FIELDS = """
    b.BookID as FileName,
    upper(b.Lang) as SearchLang,
    b.Title,
    b.FileSize as BookSize,
    b.Year as SearchYear,
    case 
      when b.FileSize <= 800 * 1024 then 'less800'
      when b.FileSize > 800 * 1024 then 'more800'
    end as BookSizeCat,  
    an.LastName,
    an.FirstName, 
    an.MiddleName,
    an.AvtorId as AuthorID,
    gl.GenreDesc AS Genre,
    sn.SeqName as SeriesTitle, 
    sn.SeqId as SeriesID, 
    ROUND(COALESCE(r.LibRate, 0)) as LibRate
"""

# Базовые JOIN (БЕЗ FROM)
BASE_JOINS = """
LEFT JOIN (select bookid, min(avtorid) as avtorid from libavtor group by bookid) a ON a.BookID = b.BookID 
LEFT JOIN libavtorname an ON an.AvtorID = a.AvtorID
LEFT JOIN (select bookid, min(genreid) as genreid from libgenre group by bookid) g ON g.BookID = b.BookID
LEFT JOIN libgenrelist gl ON gl.GenreID = g.GenreID
LEFT JOIN libseq s ON s.BookID = b.BookID
LEFT JOIN libseqname sn on sn.SeqID = s.SeqID
LEFT JOIN (
    SELECT BookId, AVG(CAST(Rate AS SIGNED)) as LibRate
    FROM librate 
    GROUP BY BookId
) r ON r.BookId = b.BookId
"""

# Основной полнотекстовый поиск
SQL_QUERY_BOOKS = f"""
select * from (
SELECT 
    {BASE_FIELDS},
    MATCH(fts.FT) AGAINST(%s IN BOOLEAN MODE) as Relevance
FROM libbook_fts fts
JOIN libbook b ON b.BookID = fts.BookID
{BASE_JOINS}
WHERE b.Deleted = '0'
  AND MATCH(fts.FT) AGAINST(%s IN BOOLEAN MODE)
) as subq 
"""

# Поиск по аннотациям книг
SQL_QUERY_ABOOKS = f"""
select * from (
SELECT 
    {BASE_FIELDS},
    MATCH(ba.Body) AGAINST(%s IN BOOLEAN MODE) as Relevance
FROM libbannotations ba
JOIN libbook b ON b.BookID = ba.BookID
{BASE_JOINS}
WHERE b.Deleted = '0'
  AND MATCH(ba.Body) AGAINST(%s IN BOOLEAN MODE)
) as subq2
"""

# Поиск по аннотациям книг
SQL_QUERY_AAUTHORS = f"""
select * from (
SELECT 
    {BASE_FIELDS},
    MATCH(aa.Body) AGAINST(%s IN BOOLEAN MODE) as Relevance
FROM libaannotations aa
JOIN libavtor ab ON ab.AvtorId = aa.AvtorId
JOIN libbook b ON b.BookID = ab.BookID
{BASE_JOINS}
WHERE b.Deleted = '0'
  AND MATCH(aa.Body) AGAINST(%s IN BOOLEAN MODE)
) as subq2
"""

SELECT_SQL_QUERY = {
    SETTING_SEARCH_AREA_B: SQL_QUERY_BOOKS,
    SETTING_SEARCH_AREA_BA: SQL_QUERY_ABOOKS,
    SETTING_SEARCH_AREA_AA: SQL_QUERY_AAUTHORS
}

SQL_QUERY_PARENT_GENRES_COUNT = """
	select coalesce(gl.GenreMeta,'Неотсортированное'), count(b.BookId)
      from libbook b
        left outer join libgenre g on g.BookId = b.BookId 
        left outer join libgenrelist gl on gl.GenreId = g.GenreId 
    where b.Deleted = '0'
      -- AND (#s = '' OR b.Lang = #s)
    group by coalesce(gl.GenreMeta, 'Неотсортированное')
    order by 1
"""

SQL_QUERY_CHILDREN_GENRES_COUNT = """
	select gl.GenreDesc, count(g.BookId), 
	  gl.GenreId
      from libbook b
	    left outer join libgenre g on g.BookId = b.BookId 
        left outer join libgenrelist gl on gl.GenreId = g.GenreId 
    Where 
      b.Deleted = '0'
      and gl.GenreMeta = %s
    group by gl.GenreDesc, gl.GenreId
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
    # UserSettingsType = namedtuple('UserSettingsType',
    #                           ['User_ID', 'MaxBooks', 'Lang', 'DateSortOrder', 'BookFormat', 'LastNewsDate',
    #                            'IsBlocked', 'BookSize', 'SearchType', 'Rating', 'SearchArea'])

    def __init__(self, db_path = FLIBUSTA_DB_SETTINGS_PATH):
        super().__init__(db_path)

    # def _initialize_database(self):
    #     """Инициализирует БД настроек при первом подключении"""
    #     with self.connect() as conn:
    #         cursor = conn.cursor()
    #
    #         # Создаем таблицу если не существует
    #         cursor.execute("""
    #             CREATE TABLE IF NOT EXISTS UserSettings (
    #                 User_ID INTEGER NOT NULL UNIQUE,
    #                 MaxBooks INTEGER NOT NULL DEFAULT 20,
    #                 Lang VARCHAR(2) DEFAULT '',
    #                 DateSortOrder VARCHAR(10) DEFAULT 'DESC',
    #                 BookFormat VARCHAR(5) DEFAULT 'fb2',
    #                 LastNewsDate VARCHAR(10) DEFAULT '2000-01-01',
    #                 IsBlocked BOOLEAN DEFAULT FALSE,
    #                 BookSize TEXT DEFAULT '',
    #                 SearchType TEXT DEFAULT 'books',
    #                 Rating TEXT DEFAULT '',
    #                 SearchArea TEXT DEFAULT 'b',
    #                 PRIMARY KEY(User_ID)
    #             );
    #         """)
    #
    #         # Создаем индекс если не существует
    #         cursor.execute("""
    #             CREATE UNIQUE INDEX IF NOT EXISTS IXUserSettings_User_ID
    #             ON UserSettings (User_ID);
    #         """)
    #
    #         conn.commit()

    def get_user_settings(self,user_id):
        """
        Получает настройки пользователя из базы данных.
        """
        fields = UserSettingsType._fields
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
        return UserSettingsType(*settings)

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

    # def get_user_stats(self):
    #     """Возвращает статистику пользователей"""
    #     with self.connect() as conn:
    #         cursor = conn.cursor()
    #
    #         # Общая статистика
    #         cursor.execute("""
    #             SELECT
    #                 COUNT(*) as total_users,
    #                 SUM(CASE WHEN IsBlocked THEN 1 ELSE 0 END) as blocked_users,
    #                 SUM(CASE WHEN LastNewsDate > '2000-01-01' THEN 1 ELSE 0 END) as active_users
    #             FROM UserSettings
    #         """)
    #         stats = cursor.fetchone()
    #
    #         return {
    #             'total_users': stats[0],
    #             'blocked_users': stats[1],
    #             'active_users': stats[2]
    #         }



# Класс для работы с БД библиотеки
class DatabaseBooks():
    _class_cached_langs = None
    _class_cached_parent_genres = None
    _class_cached_genres = {}  # Словарь для кеширования жанров по родительским категориям

    def __init__(self, db_config):
        self.db_config = db_config
        self._connection = None

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
                DatabaseBooks._class_cached_genres[parent_genre] = results #[(genre[0].strip(), genre[1]) for genre in results if genre[0].strip()]
        return DatabaseBooks._class_cached_genres[parent_genre]


    def get_langs(self):
        """Получает языки с кешированием"""
        if DatabaseBooks._class_cached_langs is None:
            with self.connect() as conn:
                cursor = conn.cursor(buffered=True)
                cursor.execute(SQL_QUERY_LANGS)
                DatabaseBooks._class_cached_langs = cursor.fetchall()
        return DatabaseBooks._class_cached_langs


    def search_books(self, query, lang, size_limit, rating_filter=None, search_area=SETTING_SEARCH_AREA_B, series_id=0, author_id=0):
        """Ищем книги по запросу пользователя"""
        sql_where = self.build_sql_where_ft(lang, size_limit, rating_filter, series_id, author_id)
        # Строим запросы для поиска книг и подсчёта количества найденных книг
        # sql_query, sql_query_cnt = self.build_sql_queries_ft(sql_where, sort_order, search_area)
        sql_query = self.build_sql_queries_ft(sql_where, 'desc', search_area)

        params = []
        # Пара одинаковых параметров в виде полного запроса для FullText поиска
        params.extend([query] * 2)

        # #DEBUG
        # print(f"DEBUG: sql_query = {sql_query}")
        # print(f"DEBUG: params = {params}")

        # выполняем запросы поиска книг и подсчёта количества найденных книг
        with self.connect() as conn:
            # conn.create_function("REMOVE_PUNCTUATION", 1, remove_punctuation)
            cursor = conn.cursor(buffered=True)
            cursor.execute(sql_query, params)
            books = [Book(*row) for row in cursor.fetchall()]
            # cursor.execute(sql_query_cnt, params)
            # count = cursor.fetchone()[0]
            # count = len(books)

        return books


    async def get_book_info(self, book_id):
        """Получает основную информацию о книге"""
        with self.connect() as conn:
            cursor = conn.cursor(buffered=True)
            cursor.execute("""
                SELECT b.Title, b.Year, sn.SeqName,
                       GROUP_CONCAT(DISTINCT CONCAT(gl.GenreID, ',', gl.GenreDesc) SEPARATOR ',') as Genres,
                       GROUP_CONCAT(DISTINCT CONCAT(an.AvtorID, ',', an.LastName, ' ', an.FirstName, ' ', an.MiddleName) SEPARATOR ',') as Authors,
                       bp.File, b.FileSize, b.Pages, b.Lang, r.LibRate, b.BookId,
                       sn.SeqID
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
            # cover_url = f"{FLIBUSTA_BASE_URL}/ib/{result[5]}" if result[5] else None
            cover_url = FlibustaClient.get_cover_url_direct(result[5]) if result[5] else None
            # print(f"DEBUG: cover_url = {cover_url}")
            # Получение ссылки на обложку со страницы книги, если нет в БД
            if cover_url is None:
                # cover_url = await get_cover_url(book_id)
                cover_url = await flibusta_client.get_book_cover_url(book_id)
                # print(f"DEBUG: cover_url = {cover_url}")

            return {
                'title': result[0],
                'year': result[1],
                'series': result[2],
                'genres': result[3],
                'authors': result[4],
                'cover_url': cover_url,
                'size': result[6],
                'pages': result[7],
                'lang': result[8],
                'rate': result[9],
                'bookid': result[10],
                'seqid': result[11],
            } if result else None

    async def get_book_details(self, book_id):
        """Получает детальную информацию о книге с обложкой и аннотацией"""
        with self.connect() as conn:
            cursor = conn.cursor(buffered=True)

            # Получаем аннотацию
            cursor.execute("""
                SELECT b.title, ba.Body FROM libbannotations ba 
                INNER JOIN libbook b ON ba.BookId = b.BookId
                WHERE ba.BookID = %s
                """, (book_id,))
            annotation_result = cursor.fetchone()

            return {
                'title': annotation_result[0],
                'annotation': annotation_result[1]
            } if annotation_result else None


    def search_series(self, query, lang, size_limit, rating_filter=None, search_area=SETTING_SEARCH_AREA_B, sort_order=None, series_id=0, author_id=0):
        """Ищет серии по запросу"""
        sql_where = self.build_sql_where_ft(lang, size_limit, rating_filter)

        params = []
        # Пара одинаковых параметров в виде полного запроса для FullText поиска
        params.extend([query] * 2)

        # запрос для поиска серий

        sql_query_nested = SELECT_SQL_QUERY.get(search_area)
        sql_query = f"""
        SELECT 
            SeriesTitle, 
            SeriesID,
            COUNT(DISTINCT FileName) as book_count
        FROM ({sql_query_nested} {sql_where}
          ORDER BY relevance DESC) as subquery
        WHERE SeriesTitle IS NOT NULL
        GROUP BY SeriesTitle, SeriesID 
        ORDER BY book_count DESC, SeriesTitle
        LIMIT {MAX_BOOKS_SEARCH}
        """

        # sql_query_cnt = f"SELECT COUNT(*) FROM ({sql_query}) as subquery2"

        # #DEBUG
        # print(f"DEBUG: sql_query = {sql_query}")
        # print(f"DEBUG: params = {params}")

        with self.connect() as conn:
            cursor = conn.cursor(buffered=True)
            cursor.execute(sql_query, params)
            series = cursor.fetchall()
            # cursor.execute(sql_query_cnt, params)
            # count = cursor.fetchone()[0]
            # count = len(series)

        return series


    async def get_authors_id(self, book_id: int) -> list[ int | None | Any] | None:
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


    async def get_author_info(self, author_id: int) -> dict[str, str | None | Any] | None:
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
            # photo_url = f"{FLIBUSTA_BASE_URL}/ia/{photo_result[0]}" if photo_result else None
            photo_url = FlibustaClient.get_author_photo_url(photo_result[0]) if photo_result else None

            # Получаем аннотацию автора
            cursor.execute("SELECT title, Body FROM libaannotations WHERE AvtorID = %s", (author_id,))
            annotation_result = cursor.fetchone()

            return {
                'name': f"{author_result[1]} {author_result[2]} {author_result[3]}",
                'photo_url': photo_url,
                'title': annotation_result[0],
                'biography': annotation_result[1],
                'author_id': author_result[0]
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


    def search_authors(self, query, lang, size_limit, rating_filter=None, search_area=SETTING_SEARCH_AREA_B, sort_order=None, series_id=0, author_id=0):
        """Ищет авторов по запросу"""
        sql_where = self.build_sql_where_ft(lang, size_limit, rating_filter)

        params = []
        # Пара одинаковых параметров в виде полного запроса для FullText поиска
        params.extend([query] * 2)

        # Модифицируем запрос для поиска авторов
        sql_query_nested = SELECT_SQL_QUERY.get(search_area)
        sql_query = f"""
        SELECT 
            CONCAT(COALESCE(LastName, ''), ' ', COALESCE(FirstName, ''), ' ', COALESCE(MiddleName, '')) as AuthorName,
            COUNT(DISTINCT FileName) as book_count,
            AuthorID
        FROM ({sql_query_nested} {sql_where}) as subquery
        WHERE LastName <> '' OR FirstName <> '' OR MiddleName <> ''
        GROUP BY AuthorName, AuthorID
        ORDER BY book_count DESC, AuthorName
        LIMIT {MAX_BOOKS_SEARCH}
        """

        # sql_query_cnt = f"SELECT COUNT(*) FROM ({sql_query}) as subquery2"

        with self.connect() as conn:
            cursor = conn.cursor(buffered=True)
            cursor.execute(sql_query, params)
            authors = cursor.fetchall()
            # cursor.execute(sql_query_cnt, params)
            # count = cursor.fetchone()[0]
            # count = len(authors)

        return authors


    @staticmethod
    def build_sql_where_ft(lang, size_limit, rating_filter=None, series_id=0, author_id=0):
        """Создает SQL-условие WHERE на основе списка слов и их операторов."""
        conditions = []

        # Добавляем условие по языку, если задан в настройках пользователя
        if lang:
            conditions.append(f"SearchLang LIKE '{lang.upper()}'")

        # Добавляем ограничение по размеру книг, если задан в настройках пользователя
        if size_limit:
            conditions.append(f"BookSizeCat = '{size_limit}'")

        # ДОБАВЛЯЕМ ФИЛЬТРАЦИЮ ПО РЕЙТИНГУ
        if rating_filter and rating_filter != '':
            rating_condition = f"LibRate IN ({rating_filter})"
            conditions.append(rating_condition)

        # Добавляем условие по серии в поиске книг по сериям
        if series_id != 0:
            conditions.append(f"SeriesID = {series_id}")

        # Добавляем условие по автору в поиске книг по авторам
        if author_id != 0:
            conditions.append(f"AuthorID = {author_id}")

        # в соновном sql вконце уже есть where, поэтому заменяем его на and
        sql_where = "WHERE " + " AND ".join(conditions) if conditions else ""
        return sql_where #, params


    @staticmethod
    def build_sql_queries_ft(sql_where, sort_order='desc', search_area=SETTING_SEARCH_AREA_B):
        fields = Book._fields

        # Всегда используем sum для Relevance
        processed_fields = []
        for field in fields:
            # processed_fields.append(f"max({field})")
            processed_fields.append(f"{field}")

        select_fields = ', '.join(processed_fields)

        sql_query_nested = SELECT_SQL_QUERY.get(search_area)
        from_clause = f"FROM ( {sql_query_nested} {sql_where} ) as subquery"

        # if search_area == SETTING_SEARCH_AREA_BA:
        #     # Основной запрос поиска по аннотации книг
        #     from_clause = f"FROM ( {SQL_QUERY_ABOOKS} {sql_where} ) as subquery"
        # else:
        #     # Основной запрос поиска по основной информации книг
        #     from_clause = f"FROM ( {SQL_QUERY_BOOKS} {sql_where} ) as subquery"

        sql_query = f"""
            SELECT {select_fields} 
            {from_clause}
            -- GROUP BY {fields[0]}
            ORDER BY Relevance DESC, FileName {sort_order}
            LIMIT {MAX_BOOKS_SEARCH}
        """

        # """ f"SELECT COUNT(*) FROM(SELECT {select_fields} {from_clause} GROUP BY {fields[0]}) as subquery2" """
        # sql_query_cnt = f"""
        #     SELECT COUNT(*) FROM ({sql_query}) as subquery2
        # """

        return sql_query #, sql_query_cnt

DB_BOOKS = DatabaseBooks({
    'host': os.getenv('DB_HOST'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'charset': os.getenv('DB_CHARSET', 'utf8mb4')
})