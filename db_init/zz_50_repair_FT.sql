-- Перестроить FULLTEXT индексы
REPAIR TABLE libbook_fts QUICK;
OPTIMIZE TABLE libbook_fts;