-- ESQUEMA DE BASE DE DATOS OPTIMIZADO PARA MATRIZ INTEGRADA (v3)

-- 1. USUARIOS Y ROLES
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT CHECK (role IN ('FINANZAS', 'LEGAL', 'COORD', 'GOBIERNO')) NOT NULL,
    avatar_url TEXT
);

-- 2. PRODUCTOS CONTRACTUALES (Agrupadores de Pago)
CREATE TABLE contract_products (
    code TEXT PRIMARY KEY, -- Ej: '1.1', '2.1', 'TRANS'
    name TEXT
);

INSERT INTO contract_products (code, name) VALUES 
('1.1', 'Coordinación y Género'), ('2.1', 'Mecanismos Financiación'), 
('2.2', 'Línea Base y Operación'), ('3.1', 'Regulación Legal'), 
('3.2', 'Inclusión Normativa'), ('TRANS', 'Transversal/Gestión');

-- 3. ACTIVIDADES (Espejo exacto del CSV nuevo)
CREATE TABLE activities (
    id SERIAL PRIMARY KEY,
    activity_code TEXT UNIQUE NOT NULL, -- El ID del CSV (Ej: 'P-2.1-07')
    product_code TEXT REFERENCES contract_products(code), -- Columna 'Producto'
    task_name TEXT NOT NULL, -- Columna 'Actividad'
    week_start INT, -- Columna 'Sem. inicio'
    week_end INT, -- Columna 'Sem. fin'
    type_tag TEXT, -- Columna 'Tipo' (INT, IND, DEP)
    
    -- Dependencias
    dependency_code TEXT, -- Columna 'Depende de' (Ej: 'T-0.1')
    
    -- Evidencias
    evidence_requirement TEXT, -- Columna 'Evidencia' (Lo que el usuario debe leer)
    
    -- Responsables
    primary_role TEXT NOT NULL, -- Columna 'Resp. primario' (Mapeado a roles)
    co_responsibles TEXT, -- Columna 'Co-responsables' (Texto libre)
    
    -- Estado del Sistema
    status TEXT DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'IN_PROGRESS', 'BLOCKED', 'DONE')),
    has_file_uploaded BOOLEAN DEFAULT FALSE
);

-- 4. EVIDENCIAS / ARCHIVOS
CREATE TABLE evidence_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    activity_id INT REFERENCES activities(id),
    uploader_id UUID REFERENCES users(id),
    file_url TEXT NOT NULL,
    file_name TEXT NOT NULL,
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 5. MECANISMOS (Pipeline de Validación)
CREATE TABLE mechanisms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    status_pipeline TEXT DEFAULT 'DRAFT', -- DRAFT -> LEGAL_REVIEW -> GENDER_REVIEW -> READY
    created_by UUID REFERENCES users(id)
);