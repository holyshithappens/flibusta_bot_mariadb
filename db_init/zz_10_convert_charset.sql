-- db_init/sql/00_convert_charset.sql
-- SET FOREIGN_KEY_CHECKS=0;

ALTER DATABASE flibusta CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;

ALTER TABLE libbook CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE libavtor CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE libavtorname CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE libseq CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE libseqname CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE libgenre CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE libgenrelist CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE libapics CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE libgenretranslate CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE libbannotations CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE libreviews CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE libtranslator CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE librecs CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE librate CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE libfilename CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE libaannotations CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE libbpics CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
ALTER TABLE libjoinedbooks CONVERT TO CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;

-- SET FOREIGN_KEY_CHECKS=1;

