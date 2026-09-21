-- Pending one-time email verification codes (email-code verification). Transient: one row per user,
-- superseded by a newer request and deleted on success, expiry or /forget-me.
CREATE TABLE email_codes (
  user_id       INTEGER PRIMARY KEY,
  login         TEXT NOT NULL,
  email         TEXT NOT NULL,        -- where the code was sent (transient; not kept after the code is used)
  subject_hmac  BLOB NOT NULL,        -- keyed hash of <AIS ID or login>@domain, bound on success
  code_hash     BLOB NOT NULL,        -- SHA-256 of the code; the code itself is never stored
  outcome       TEXT NOT NULL CHECK (outcome IN ('student', 'teacher', 'review')),
  attempts      INTEGER NOT NULL DEFAULT 0,
  created_at    INTEGER NOT NULL,
  expires_at    INTEGER NOT NULL
);
