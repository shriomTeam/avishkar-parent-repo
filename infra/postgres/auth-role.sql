-- Local development only; safe for an existing parent volume, no data reset.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'clinic_auth') THEN
        CREATE ROLE clinic_auth LOGIN PASSWORD 'clinic_auth';
    ELSE
        ALTER ROLE clinic_auth LOGIN PASSWORD 'clinic_auth';
    END IF;
END $$;
GRANT CONNECT ON DATABASE clinic TO clinic_auth;
