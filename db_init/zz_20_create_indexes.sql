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