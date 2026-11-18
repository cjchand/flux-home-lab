-- Inventory of a Teslamate database, printed as sorted lines so two servers
-- can be compared with diff. Run with: psql -At -f scripts/pg-inventory.sql
--
--   table|<schema>.<table>|<exact row count>
--   seq|<schema>.<seq>|ok   (or BEHIND <last_value> < <max>)
--   ext|<name>|<version>
--   migration|<max schema_migrations.version>
--
-- Builds one UNION query and runs it with \gexec so a single ORDER BY
-- covers every line.

SELECT string_agg(q, E'\nUNION ALL\n') || E'\nORDER BY 1'
FROM (
  SELECT format(
           'SELECT %L || count(*) FROM %I.%I',
           'table|' || schemaname || '.' || tablename || '|',
           schemaname, tablename) AS q
  FROM pg_tables
  WHERE schemaname IN ('public', 'private')

  UNION ALL

  -- A sequence is ok when the next value it hands out is above max(column).
  SELECT format(
           $f$SELECT %L || CASE
                WHEN (SELECT max(%I) FROM %I.%I) IS NULL
                  OR (SELECT CASE WHEN is_called THEN last_value + 1 ELSE last_value END FROM %I.%I)
                     > (SELECT max(%I) FROM %I.%I)
                THEN 'ok'
                ELSE 'BEHIND ' || (SELECT last_value FROM %I.%I) || ' < ' || (SELECT max(%I) FROM %I.%I)
              END$f$,
           'seq|' || sn.nspname || '.' || s.relname || '|',
           a.attname, tn.nspname, t.relname,
           sn.nspname, s.relname,
           a.attname, tn.nspname, t.relname,
           sn.nspname, s.relname,
           a.attname, tn.nspname, t.relname)
  FROM pg_class s
  JOIN pg_namespace sn ON sn.oid = s.relnamespace
  JOIN pg_depend d ON d.classid = 'pg_class'::regclass
                  AND d.objid = s.oid
                  AND d.refclassid = 'pg_class'::regclass
                  AND d.deptype IN ('a', 'i')
  JOIN pg_class t ON t.oid = d.refobjid
  JOIN pg_namespace tn ON tn.oid = t.relnamespace
  JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
  WHERE s.relkind = 'S'
    AND sn.nspname IN ('public', 'private')

  UNION ALL

  SELECT $q$SELECT 'ext|' || extname || '|' || extversion FROM pg_extension WHERE extname <> 'plpgsql'$q$

  UNION ALL

  SELECT $q$SELECT 'migration|' || max(version) FROM public.schema_migrations$q$
) parts
\gexec
