-- update_schema_v5.sql

CREATE TABLE IF NOT EXISTS project_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT
);

INSERT INTO project_meta (key, value, description) VALUES
('project_name', 'Gestión Integrada GWP/NDC', 'Nombre público del proyecto'),
('start_date', '2023-10-01', 'Fecha ancla para el cálculo de semanas'),
('logo_url', 'https://placehold.co/200x50/png?text=GWP+Logo', 'URL del logotipo')
ON CONFLICT (key) DO NOTHING;
