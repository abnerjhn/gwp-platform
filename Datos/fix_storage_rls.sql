-- FIX STORAGE RLS (Crucial for File Uploads)

-- 1. Allow access to the 'evidence' bucket in storage.objects
-- This is separate from the public.evidence_files table!

BEGIN;

-- Policy for INSERT (Upload)
CREATE POLICY "Allow uploads to evidence bucket"
ON storage.objects
FOR INSERT
TO public
WITH CHECK (bucket_id = 'evidence');

-- Policy for SELECT (Download)
CREATE POLICY "Allow public downloads from evidence bucket"
ON storage.objects
FOR SELECT
TO public
USING (bucket_id = 'evidence');

-- Policy for UPDATE/DELETE
CREATE POLICY "Allow update/delete in evidence bucket"
ON storage.objects
FOR ALL
USING (bucket_id = 'evidence');

COMMIT;
