-- Enable extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Patients table
CREATE TABLE patients (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    age INTEGER NOT NULL CHECK (age >= 0 AND age <= 120),
    sex VARCHAR(10) NOT NULL CHECK (sex IN ('male', 'female')),
    weight_kg FLOAT,
    known_conditions JSONB DEFAULT '[]'::jsonb,
    medications JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Guideline documents metadata
CREATE TABLE guideline_docs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(500) NOT NULL,
    source VARCHAR(255) NOT NULL,
    publication_date DATE,
    category VARCHAR(100) DEFAULT 'pediatric',
    file_path VARCHAR(1000),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Chunks with vector embeddings
CREATE TABLE chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    doc_id UUID NOT NULL REFERENCES guideline_docs(id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    embedding vector(384),
    section_type VARCHAR(100),
    age_range VARCHAR(50) DEFAULT 'pediatric',
    condition_category VARCHAR(100),
    page_num INTEGER,
    chunk_index INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for chunks
CREATE INDEX idx_chunks_embedding ON chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX idx_chunks_filters ON chunks (age_range, condition_category);
CREATE INDEX idx_chunks_doc_id ON chunks (doc_id);

-- Conversations
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    summary TEXT
);

-- Messages within conversations
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    citations JSONB DEFAULT '[]'::jsonb,
    confidence_score FLOAT,
    refused BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_messages_conversation ON messages (conversation_id, created_at);

-- Symptom extractions from messages
CREATE TABLE symptom_extractions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    symptoms JSONB DEFAULT '[]'::jsonb,
    severity_estimate VARCHAR(20) DEFAULT 'unknown'
        CHECK (severity_estimate IN ('mild', 'moderate', 'severe', 'unknown')),
    extracted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Events for analytics/MLOps
CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    patient_id UUID REFERENCES patients(id) ON DELETE SET NULL,
    event_type VARCHAR(50) NOT NULL,
    payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_events_type_time ON events (event_type, created_at);

-- Logged medication doses (#3: dose log + double-dose guard). Mirrors the SQLAlchemy Dose model.
CREATE TABLE doses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    drug VARCHAR(100) NOT NULL,
    amount_mg FLOAT,
    given_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    note VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- The guard queries a patient's doses ordered by time, so index on both.
CREATE INDEX idx_doses_patient_time ON doses (patient_id, given_at);

-- Seed a demo patient
INSERT INTO patients (name, age, sex, weight_kg, known_conditions, medications)
VALUES (
    'Demo Child',
    4,
    'female',
    16.0,
    '["mild eczema"]'::jsonb,
    '[]'::jsonb
);