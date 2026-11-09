CREATE TABLE jurisdictions (
  jurisdiction_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  level TEXT NOT NULL CHECK (level IN ('federal','state'))
);
CREATE TABLE election_cycles (
  election_id TEXT PRIMARY KEY,
  jurisdiction_id TEXT NOT NULL REFERENCES jurisdictions(jurisdiction_id),
  election_date DATE,
  chamber TEXT NOT NULL,
  boundary_version TEXT NOT NULL,
  source_url TEXT
);
CREATE TABLE electorates (
  electorate_id TEXT PRIMARY KEY,
  jurisdiction_id TEXT NOT NULL REFERENCES jurisdictions(jurisdiction_id),
  chamber TEXT NOT NULL,
  electorate_name TEXT NOT NULL,
  boundary_version TEXT NOT NULL,
  source_url TEXT
);
CREATE TABLE election_results (
  result_id BIGSERIAL PRIMARY KEY,
  election_id TEXT NOT NULL REFERENCES election_cycles(election_id),
  electorate_id TEXT NOT NULL REFERENCES electorates(electorate_id),
  candidate TEXT,
  party TEXT,
  vote_type TEXT NOT NULL,
  votes BIGINT,
  vote_share NUMERIC(8,5),
  source_url TEXT NOT NULL,
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE observations (
  observation_id BIGSERIAL PRIMARY KEY,
  source_id TEXT NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  published_at TIMESTAMPTZ,
  geography_type TEXT,
  geography_id TEXT,
  topic TEXT,
  entity TEXT,
  raw_value JSONB NOT NULL,
  source_url TEXT NOT NULL,
  licence_notes TEXT,
  UNIQUE(source_id, observed_at, geography_id, topic, entity, source_url)
);
CREATE TABLE sentiment_scores (
  score_id BIGSERIAL PRIMARY KEY,
  observation_id BIGINT NOT NULL REFERENCES observations(observation_id),
  target_type TEXT NOT NULL,
  target_name TEXT,
  issue TEXT,
  sentiment_label TEXT CHECK (sentiment_label IN ('positive','negative','neutral','mixed','unclear')),
  sentiment_value NUMERIC(5,4),
  confidence NUMERIC(5,4),
  classifier_version TEXT NOT NULL,
  human_reviewed BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE indicator_series (
  indicator_id BIGSERIAL PRIMARY KEY,
  electorate_id TEXT NOT NULL REFERENCES electorates(electorate_id),
  week_start DATE NOT NULL,
  indicator_name TEXT NOT NULL,
  value NUMERIC,
  denominator NUMERIC,
  coverage NUMERIC(5,4),
  source_count INTEGER NOT NULL DEFAULT 0,
  methodology_version TEXT NOT NULL,
  UNIQUE(electorate_id, week_start, indicator_name, methodology_version)
);
