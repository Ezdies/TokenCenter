SELECT 'CREATE DATABASE langfuse OWNER token_center'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
