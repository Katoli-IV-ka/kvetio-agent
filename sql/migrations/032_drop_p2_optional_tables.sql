-- 032_drop_p2_optional_tables.sql
-- Remove P2 tables that were applied prematurely. The current pipeline keeps
-- funding data on dossiers and does not model inter-company relations.

DROP TABLE IF EXISTS company_relations;
DROP TABLE IF EXISTS funding_rounds;
