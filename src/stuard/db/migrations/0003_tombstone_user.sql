-- Record which Discord user a tombstone came from, so a moderator can clear it (/mod readmit)
-- after a /forget-me or unlink without needing the (now-deleted) STU identity. Older rows stay NULL.
ALTER TABLE tombstones ADD COLUMN user_id INTEGER;
