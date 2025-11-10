-- db_init/sql/00_convert_charset.sql
-- SET FOREIGN_KEY_CHECKS=0;

ALTER DATABASE flibusta CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

ALTER TABLE libbook CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE libavtor CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE libavtorname CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE libseq CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE libseqname CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE libgenre CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE libgenrelist CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE libapics CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE libgenretranslate CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE libbannotations CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE libreviews CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE libtranslator CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE librecs CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE librate CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE libfilename CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE libaannotations CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE libbpics CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER TABLE libjoinedbooks CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- SET FOREIGN_KEY_CHECKS=1;

-- Для libreviews
CREATE INDEX idx_libreviews_bookid_time_desc ON libreviews (BookId ASC, Time DESC); -- есть дубликаты
-- Для libapics
CREATE INDEX idx_libapics_avtorid ON libapics (AvtorId ASC); -- есть дубликаты
-- Для libaannotations
CREATE INDEX idx_libaannotations_avtorid ON libaannotations (AvtorId ASC); -- есть дубликаты
-- Для libbannotations
CREATE INDEX idx_libbannotations_bookid ON libbannotations (BookId ASC); -- есть дубликаты
-- Для libbpics
CREATE INDEX idx_libbpics_bookid ON libbpics (BookId ASC); -- есть дубликаты