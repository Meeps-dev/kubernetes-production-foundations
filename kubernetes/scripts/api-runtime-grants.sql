-- Executed inside the first-time runtime-role transaction by the helper.
-- Only the operations exposed by the current API are granted.
\getenv database_name POSTGRES_DB
GRANT CONNECT ON DATABASE :"database_name" TO meeps_api;
GRANT USAGE ON SCHEMA public TO meeps_api;
GRANT SELECT, INSERT ON TABLE public.users, public.posts TO meeps_api;

-- INSERT on a SERIAL-backed table also needs its sequence privilege.
-- Discover sequence names instead of assuming them.
SELECT format('GRANT USAGE ON SEQUENCE %s TO meeps_api;', sequence_name)
FROM (
  SELECT pg_get_serial_sequence(table_name, 'id') AS sequence_name
  FROM (VALUES ('public.users'), ('public.posts')) AS tables(table_name)
) AS sequences
WHERE sequence_name IS NOT NULL
\gexec

-- No migration-table privileges, ownership, UPDATE/DELETE, or blanket
-- privileges on future tables. Add reviewed grants when the API needs them.
