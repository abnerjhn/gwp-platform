-- update_schema_v4.sql

-- 1. Tabla de Configuración del Proyecto
CREATE TABLE IF NOT EXISTS project_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Insertar valores por defecto si no existen
INSERT INTO project_config (key, value) VALUES
('project_name', 'Gestión Integrada GWP/NDC'),
('start_date', '2023-10-01'),
('logo_url', 'https://placehold.co/200x50/png?text=GWP+Logo')
ON CONFLICT (key) DO NOTHING;

-- 2. Asegurar Tabla de Mecanismos (si no se creó antes)
CREATE TABLE IF NOT EXISTS mechanisms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    status_pipeline TEXT DEFAULT 'DRAFT' CHECK (status_pipeline IN ('DRAFT', 'LEGAL_REVIEW', 'GENDER_REVIEW', 'APPROVED')),
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
