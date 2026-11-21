-- SQLite Vector & Lightweight Graph Schema with Multi-Project Support

-- 1. 태스크 기본 메타데이터
CREATE TABLE IF NOT EXISTS tasks (
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    title TEXT,
    status TEXT,
    owner TEXT,
    priority TEXT,
    level INTEGER,
    created_at TEXT,
    updated_at TEXT,
    completed_at TEXT,
    PRIMARY KEY (project_id, task_id)
);

-- 2. 경량 그래프 관계 테이블 (프로젝트 스코프 내 관계 추적)
CREATE TABLE IF NOT EXISTS task_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    relation_type TEXT NOT NULL, -- 'modified_file', 'depends_on', 'subtask_of', 'supersedes', 'related_to', 'touches_symbol', 'artifact', 'assigned_agent'
    target TEXT NOT NULL,
    UNIQUE(project_id, task_id, relation_type, target)
);

CREATE INDEX IF NOT EXISTS idx_task_relations_proj_target ON task_relations(project_id, target);
CREATE INDEX IF NOT EXISTS idx_task_relations_proj_type ON task_relations(project_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_task_relations_task_type ON task_relations(project_id, task_id, relation_type);

-- 3. 마크다운 헤더 기반 청크 및 밀집 벡터 저장소
CREATE TABLE IF NOT EXISTS task_chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    header_path TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding BLOB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_task_chunks_proj_task ON task_chunks(project_id, task_id);

-- 4. FTS5 전문 검색 테이블 (키워드 매칭용 가상 테이블)
CREATE VIRTUAL TABLE IF NOT EXISTS task_chunks_fts USING fts5(
    chunk_id UNINDEXED,
    project_id,
    task_id,
    file_name,
    header_path,
    content,
    tokenize='unicode61'
);

-- 5. 코드 엔티티 및 심볼 노드 (Code Entity & Symbol Graph)
CREATE TABLE IF NOT EXISTS code_entities (
    entity_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    entity_type TEXT NOT NULL, -- 'function', 'class', 'interface', 'endpoint', 'type', 'component'
    name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    line_number INTEGER DEFAULT 0,
    signature TEXT,
    UNIQUE(project_id, entity_type, name, file_path)
);

CREATE INDEX IF NOT EXISTS idx_code_entities_name ON code_entities(project_id, name);
CREATE INDEX IF NOT EXISTS idx_code_entities_file ON code_entities(project_id, file_path);

-- 6. 코드 간 의존/호출 엣지 (Code Dependencies & Call Graph)
CREATE TABLE IF NOT EXISTS code_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    relation_type TEXT NOT NULL, -- 'calls', 'imports', 'implements', 'references'
    target_name TEXT NOT NULL,
    file_path TEXT,
    UNIQUE(project_id, source_name, relation_type, target_name)
);

CREATE INDEX IF NOT EXISTS idx_code_rel_source ON code_relations(project_id, source_name);
CREATE INDEX IF NOT EXISTS idx_code_rel_target ON code_relations(project_id, target_name);

-- 7. 에이전트별 메모리 조회 감사 로그 (Agent Memory Access Audit Logs)
CREATE TABLE IF NOT EXISTS memory_access_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    project_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    query_text TEXT,
    target_file TEXT,
    target_symbol TEXT,
    task_id TEXT,
    result_count INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_memory_access_agent ON memory_access_logs(agent_name, accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_access_time ON memory_access_logs(accessed_at DESC);
