-- 2026_08_17_user_delete_cascade.sql
-- Fix DELETE /users FK violations: add ON DELETE SET NULL to all nullable
-- FK references to users.id, so deleting a user nullifies historical
-- references instead of raising a 500.

-- audit_logs.user_id
ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_user_id_fkey;
ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;

-- park_transactions.entry_operator_id
ALTER TABLE park_transactions DROP CONSTRAINT IF EXISTS park_transactions_entry_operator_id_fkey;
ALTER TABLE park_transactions ADD CONSTRAINT park_transactions_entry_operator_id_fkey
    FOREIGN KEY (entry_operator_id) REFERENCES users(id) ON DELETE SET NULL;

-- park_transactions.exit_operator_id
ALTER TABLE park_transactions DROP CONSTRAINT IF EXISTS park_transactions_exit_operator_id_fkey;
ALTER TABLE park_transactions ADD CONSTRAINT park_transactions_exit_operator_id_fkey
    FOREIGN KEY (exit_operator_id) REFERENCES users(id) ON DELETE SET NULL;

-- members.created_by
ALTER TABLE members DROP CONSTRAINT IF EXISTS members_created_by_fkey;
ALTER TABLE members ADD CONSTRAINT members_created_by_fkey
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;

-- backups.created_by
ALTER TABLE backups DROP CONSTRAINT IF EXISTS backups_created_by_fkey;
ALTER TABLE backups ADD CONSTRAINT backups_created_by_fkey
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;

-- backups.last_restored_by
ALTER TABLE backups DROP CONSTRAINT IF EXISTS backups_last_restored_by_fkey;
ALTER TABLE backups ADD CONSTRAINT backups_last_restored_by_fkey
    FOREIGN KEY (last_restored_by) REFERENCES users(id) ON DELETE SET NULL;
