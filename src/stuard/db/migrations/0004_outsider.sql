-- Add the "outsider" status: a verified STU student from another faculty (not MTF). SQLite cannot alter a
-- CHECK in place, so members and email_codes are rebuilt. The migration runner disables foreign keys around
-- migrations, so dropping members here does not cascade to identities / study_selection; data is copied over.

CREATE TABLE members_new (
  user_id            INTEGER PRIMARY KEY,
  status             TEXT NOT NULL DEFAULT 'unverified'
                     CHECK (status IN ('unverified', 'applicant', 'student', 'outsider', 'former_student', 'alumni')),
  is_teacher         INTEGER NOT NULL DEFAULT 0,
  method             TEXT CHECK (method IN ('sso', 'microsoft', 'manual', 'mod')),
  verified_at        INTEGER,
  valid_until        INTEGER,
  status_changed_at  INTEGER,
  left_at            INTEGER
);
INSERT INTO members_new (user_id, status, is_teacher, method, verified_at, valid_until, status_changed_at, left_at)
  SELECT user_id, status, is_teacher, method, verified_at, valid_until, status_changed_at, left_at FROM members;
DROP TABLE members;
ALTER TABLE members_new RENAME TO members;

CREATE TABLE email_codes_new (
  user_id       INTEGER PRIMARY KEY,
  login         TEXT NOT NULL,
  email         TEXT NOT NULL,
  subject_hmac  BLOB NOT NULL,
  code_hash     BLOB NOT NULL,
  outcome       TEXT NOT NULL CHECK (outcome IN ('student', 'outsider', 'teacher', 'review')),
  attempts      INTEGER NOT NULL DEFAULT 0,
  created_at    INTEGER NOT NULL,
  expires_at    INTEGER NOT NULL
);
INSERT INTO email_codes_new (user_id, login, email, subject_hmac, code_hash, outcome, attempts, created_at, expires_at)
  SELECT user_id, login, email, subject_hmac, code_hash, outcome, attempts, created_at, expires_at FROM email_codes;
DROP TABLE email_codes;
ALTER TABLE email_codes_new RENAME TO email_codes;
