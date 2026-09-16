CREATE TABLE members (
  user_id            INTEGER PRIMARY KEY,
  status             TEXT NOT NULL DEFAULT 'unverified'
                     CHECK (status IN ('unverified', 'applicant', 'student', 'former_student', 'alumni')),
  is_teacher         INTEGER NOT NULL DEFAULT 0,
  method             TEXT CHECK (method IN ('sso', 'microsoft', 'manual', 'mod')),
  verified_at        INTEGER,
  valid_until        INTEGER,
  status_changed_at  INTEGER,
  left_at            INTEGER
);

-- One UIS account <-> one Discord account. Only a keyed hash of the login is stored.
CREATE TABLE identities (
  subject_hmac      BLOB PRIMARY KEY,
  user_id           INTEGER NOT NULL UNIQUE REFERENCES members(user_id) ON DELETE CASCADE,
  affiliations      TEXT NOT NULL,
  bound_at          INTEGER NOT NULL,
  last_verified_at  INTEGER NOT NULL
);

CREATE TABLE tombstones (
  subject_hmac  BLOB PRIMARY KEY,
  expires_at    INTEGER NOT NULL
);

CREATE TABLE verify_flows (
  id                  INTEGER PRIMARY KEY,
  user_id             INTEGER NOT NULL,
  method              TEXT NOT NULL DEFAULT 'saml' CHECK (method IN ('saml', 'microsoft')),
  link_token_hash     BLOB NOT NULL UNIQUE,
  browser_token_hash  BLOB UNIQUE,
  oauth_state_hash    BLOB UNIQUE,
  -- Handed only to the browser that posted the SAML response; required together with the flow cookie.
  complete_token_hash BLOB UNIQUE,
  -- SAML RelayState or OpenID Connect state (Microsoft).
  relay_state         TEXT UNIQUE,
  saml_request_id     TEXT UNIQUE,
  nonce_hash          BLOB,
  pkce_verifier       TEXT,
  status              TEXT NOT NULL
                      CHECK (status IN ('issued', 'opened', 'oauth_ok', 'idp_sent', 'idp_ok',
                                        'completed', 'failed', 'superseded')),
  result              TEXT,
  error_code          TEXT,
  created_at          INTEGER NOT NULL,
  expires_at          INTEGER NOT NULL
);
CREATE INDEX verify_flows_user ON verify_flows(user_id);

CREATE TABLE saml_seen_assertions (
  assertion_id  TEXT PRIMARY KEY,
  expires_at    INTEGER NOT NULL
);

CREATE TABLE review_requests (
  id                INTEGER PRIMARY KEY,
  user_id           INTEGER NOT NULL,
  source            TEXT NOT NULL CHECK (source IN ('manual', 'sso_teacher', 'sso_status')),
  claimed_role      TEXT,
  sso_affiliations  TEXT,
  note              TEXT,
  status            TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')),
  channel_id        INTEGER,
  message_id        INTEGER,
  decided_by        INTEGER,
  decided_role      TEXT,
  reason            TEXT,
  created_at        INTEGER NOT NULL,
  decided_at        INTEGER
);
CREATE UNIQUE INDEX review_requests_one_pending ON review_requests(user_id, source) WHERE status = 'pending';
CREATE INDEX review_requests_status ON review_requests(status, created_at);

CREATE TABLE study_selection (
  user_id       INTEGER PRIMARY KEY REFERENCES members(user_id) ON DELETE CASCADE,
  degree        TEXT NOT NULL,
  programme_id  TEXT NOT NULL,
  year          INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL
);

CREATE TABLE role_map (
  key      TEXT PRIMARY KEY,
  role_id  INTEGER NOT NULL
);

CREATE TABLE reminders (
  user_id  INTEGER NOT NULL,
  cycle    TEXT NOT NULL,
  kind     TEXT NOT NULL,
  sent_at  INTEGER NOT NULL,
  PRIMARY KEY (user_id, cycle, kind)
);

CREATE TABLE audit (
  id         INTEGER PRIMARY KEY,
  ts         INTEGER NOT NULL,
  actor_id   INTEGER,
  target_id  INTEGER,
  action     TEXT NOT NULL,
  detail     TEXT
);
CREATE INDEX audit_ts ON audit(ts);
CREATE INDEX audit_target ON audit(target_id);

CREATE TABLE settings (
  key    TEXT PRIMARY KEY,
  value  TEXT NOT NULL
);
