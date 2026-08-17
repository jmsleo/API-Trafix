-- 2026_08_17_fk_cascade_comprehensive.sql
-- Add ON DELETE CASCADE / SET NULL to every FK that was missing it,
-- preventing 500s on DELETE for shifts, gates, vehicle_types,
-- subscription_plans, signages, park_transactions, etc.

-- === ON DELETE CASCADE (operational children — safe to delete with parent) ===

-- shifts → operator_sessions.shift_id
ALTER TABLE operator_sessions DROP CONSTRAINT IF EXISTS operator_sessions_shift_id_fkey;
ALTER TABLE operator_sessions ADD CONSTRAINT operator_sessions_shift_id_fkey
    FOREIGN KEY (shift_id) REFERENCES shifts(id) ON DELETE CASCADE;

-- shifts → operator_shift_assignments.shift_id
ALTER TABLE operator_shift_assignments DROP CONSTRAINT IF EXISTS operator_shift_assignments_shift_id_fkey;
ALTER TABLE operator_shift_assignments ADD CONSTRAINT operator_shift_assignments_shift_id_fkey
    FOREIGN KEY (shift_id) REFERENCES shifts(id) ON DELETE CASCADE;

-- gates → devices.gate_id
ALTER TABLE devices DROP CONSTRAINT IF EXISTS devices_gate_id_fkey;
ALTER TABLE devices ADD CONSTRAINT devices_gate_id_fkey
    FOREIGN KEY (gate_id) REFERENCES gates(id) ON DELETE CASCADE;

-- gates → operator_sessions.gate_id
ALTER TABLE operator_sessions DROP CONSTRAINT IF EXISTS operator_sessions_gate_id_fkey;
ALTER TABLE operator_sessions ADD CONSTRAINT operator_sessions_gate_id_fkey
    FOREIGN KEY (gate_id) REFERENCES gates(id) ON DELETE CASCADE;

-- vehicle_types → member_vehicles.vehicle_type_id
ALTER TABLE member_vehicles DROP CONSTRAINT IF EXISTS member_vehicles_vehicle_type_id_fkey;
ALTER TABLE member_vehicles ADD CONSTRAINT member_vehicles_vehicle_type_id_fkey
    FOREIGN KEY (vehicle_type_id) REFERENCES vehicle_types(id) ON DELETE CASCADE;

-- vehicle_types → parking_rates.vehicle_type_id
ALTER TABLE parking_rates DROP CONSTRAINT IF EXISTS parking_rates_vehicle_type_id_fkey;
ALTER TABLE parking_rates ADD CONSTRAINT parking_rates_vehicle_type_id_fkey
    FOREIGN KEY (vehicle_type_id) REFERENCES vehicle_types(id) ON DELETE CASCADE;

-- vehicle_types → parking_slots.vehicle_type_id
ALTER TABLE parking_slots DROP CONSTRAINT IF EXISTS parking_slots_vehicle_type_id_fkey;
ALTER TABLE parking_slots ADD CONSTRAINT parking_slots_vehicle_type_id_fkey
    FOREIGN KEY (vehicle_type_id) REFERENCES vehicle_types(id) ON DELETE CASCADE;

-- subscription_plans → member_subscriptions.plan_id
ALTER TABLE member_subscriptions DROP CONSTRAINT IF EXISTS member_subscriptions_plan_id_fkey;
ALTER TABLE member_subscriptions ADD CONSTRAINT member_subscriptions_plan_id_fkey
    FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE CASCADE;

-- members → member_vehicles.member_id  (already ORM-cascade, make DB match)
ALTER TABLE member_vehicles DROP CONSTRAINT IF EXISTS member_vehicles_member_id_fkey;
ALTER TABLE member_vehicles ADD CONSTRAINT member_vehicles_member_id_fkey
    FOREIGN KEY (member_id) REFERENCES members(id) ON DELETE CASCADE;

-- members → member_subscriptions.member_id  (already ORM-cascade, make DB match)
ALTER TABLE member_subscriptions DROP CONSTRAINT IF EXISTS member_subscriptions_member_id_fkey;
ALTER TABLE member_subscriptions ADD CONSTRAINT member_subscriptions_member_id_fkey
    FOREIGN KEY (member_id) REFERENCES members(id) ON DELETE CASCADE;

-- signages → signage_assignments.signage_id
ALTER TABLE signage_assignments DROP CONSTRAINT IF EXISTS signage_assignments_signage_id_fkey;
ALTER TABLE signage_assignments ADD CONSTRAINT signage_assignments_signage_id_fkey
    FOREIGN KEY (signage_id) REFERENCES signages(id) ON DELETE CASCADE;

-- signages → signage_schedules.signage_id
ALTER TABLE signage_schedules DROP CONSTRAINT IF EXISTS signage_schedules_signage_id_fkey;
ALTER TABLE signage_schedules ADD CONSTRAINT signage_schedules_signage_id_fkey
    FOREIGN KEY (signage_id) REFERENCES signages(id) ON DELETE CASCADE;

-- signage_contents → signage_assignments.content_id
ALTER TABLE signage_assignments DROP CONSTRAINT IF EXISTS signage_assignments_content_id_fkey;
ALTER TABLE signage_assignments ADD CONSTRAINT signage_assignments_content_id_fkey
    FOREIGN KEY (content_id) REFERENCES signage_contents(id) ON DELETE CASCADE;

-- signage_contents → signage_schedules.content_id
ALTER TABLE signage_schedules DROP CONSTRAINT IF EXISTS signage_schedules_content_id_fkey;
ALTER TABLE signage_schedules ADD CONSTRAINT signage_schedules_content_id_fkey
    FOREIGN KEY (content_id) REFERENCES signage_contents(id) ON DELETE CASCADE;

-- park_transactions → payments.park_transaction_id
ALTER TABLE payments DROP CONSTRAINT IF EXISTS payments_park_transaction_id_fkey;
ALTER TABLE payments ADD CONSTRAINT payments_park_transaction_id_fkey
    FOREIGN KEY (park_transaction_id) REFERENCES park_transactions(id) ON DELETE CASCADE;


-- === ON DELETE SET NULL (historical nullable FKs) ===

-- gates → park_transactions.exit_gate_id
ALTER TABLE park_transactions DROP CONSTRAINT IF EXISTS park_transactions_exit_gate_id_fkey;
ALTER TABLE park_transactions ADD CONSTRAINT park_transactions_exit_gate_id_fkey
    FOREIGN KEY (exit_gate_id) REFERENCES gates(id) ON DELETE SET NULL;

-- shifts → park_transactions.entry_shift_id
ALTER TABLE park_transactions DROP CONSTRAINT IF EXISTS park_transactions_entry_shift_id_fkey;
ALTER TABLE park_transactions ADD CONSTRAINT park_transactions_entry_shift_id_fkey
    FOREIGN KEY (entry_shift_id) REFERENCES shifts(id) ON DELETE SET NULL;

-- shifts → park_transactions.exit_shift_id
ALTER TABLE park_transactions DROP CONSTRAINT IF EXISTS park_transactions_exit_shift_id_fkey;
ALTER TABLE park_transactions ADD CONSTRAINT park_transactions_exit_shift_id_fkey
    FOREIGN KEY (exit_shift_id) REFERENCES shifts(id) ON DELETE SET NULL;

-- member_vehicles → park_transactions.member_vehicle_id
ALTER TABLE park_transactions DROP CONSTRAINT IF EXISTS park_transactions_member_vehicle_id_fkey;
ALTER TABLE park_transactions ADD CONSTRAINT park_transactions_member_vehicle_id_fkey
    FOREIGN KEY (member_vehicle_id) REFERENCES member_vehicles(id) ON DELETE SET NULL;

-- parking_rates → park_transactions.parking_rate_id
ALTER TABLE park_transactions DROP CONSTRAINT IF EXISTS park_transactions_parking_rate_id_fkey;
ALTER TABLE park_transactions ADD CONSTRAINT park_transactions_parking_rate_id_fkey
    FOREIGN KEY (parking_rate_id) REFERENCES parking_rates(id) ON DELETE SET NULL;
