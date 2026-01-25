-- Update Schema V6: Evidence Files

CREATE TABLE IF NOT EXISTS evidence_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    activity_code TEXT NOT NULL,
    filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    file_size BIGINT,
    content_type TEXT,
    uploaded_by TEXT,
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_evidence_activity ON evidence_files(activity_code);
