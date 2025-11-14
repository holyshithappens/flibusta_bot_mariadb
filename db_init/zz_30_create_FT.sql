-- -- ПОЛНОТЕКСТОВЫЙ ПОИСК -- --
DROP TABLE IF EXISTS libbook_fts;
CREATE TABLE libbook_fts (
    BookId INT(10) UNSIGNED NOT NULL,
    FT LONGTEXT,
    PRIMARY KEY (BookId),
    FULLTEXT idx_fts_search (FT)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_unicode_ci;

-- -- ПОЛНЕТОКСТОВЫЙ ИНДЕКС ДЛЯ ПОИСКА ПО АННОТАЦИИ КНИГ
CREATE FULLTEXT INDEX idx_annotations_body_ft ON libbannotations (Body);
