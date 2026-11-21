# /// script
# dependencies = [
#     "fastembed",
#     "numpy",
# ]
# ///

import os
import re
import sys
import json
import sqlite3
import argparse
import numpy as np
from pathlib import Path
from fastembed import TextEmbedding

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # Dev workspace root
PROJECTS_DIR = BASE_DIR / ".team" / "projects"
DB_PATH = BASE_DIR / ".team" / "memory" / "memory.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

def init_db(conn: sqlite3.Connection):
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()

def get_project_target_path(project_id: str) -> Path:
    """PROJECT.md에서 원본 코드 경로를 파싱하거나 기본 경로를 반환"""
    spec_file = PROJECTS_DIR / project_id / "PROJECT.md"
    if spec_file.exists():
        try:
            content = spec_file.read_text(encoding="utf-8")
            m = re.search(r"원본 코드 경로:\s*([^\n]+)", content)
            if m:
                p = Path(m.group(1).strip().strip('`'))
                if p.exists():
                    return p
        except Exception:
            pass
    fallback = BASE_DIR.parent / project_id
    return fallback if fallback.exists() else BASE_DIR

def extract_file_paths(text: str) -> set[str]:
    """마크다운 본문에서 언급된 소스 파일 경로를 추출"""
    patterns = [
        r'`([a-zA-Z0-9_\-\./]+\.(?:ts|tsx|js|jsx|json|md|py|sh|css|html|sql))`',
        r'(?:backend|frontend|docs|artifacts|uploads|src|app)/[a-zA-Z0-9_\-\./]+\.[a-zA-Z0-9]+'
    ]
    found = set()
    for p in patterns:
        for match in re.finditer(p, text):
            candidate = match.group(1) if match.groups() else match.group(0)
            candidate = candidate.strip().strip('`').strip('\'"')
            if any(candidate.startswith(prefix) for prefix in ("backend/", "frontend/", "docs/", "artifacts/", "uploads/", "src/", "app/", ".team/")):
                found.add(candidate)
    return found

def extract_task_dependencies(text: str, current_task_id: str) -> dict[str, set[str]]:
    """[1단계] 마크다운 본문에서 선행/의존/대체 태스크 인과 관계 추출"""
    deps = {
        "depends_on": set(),
        "supersedes": set(),
        "related_to": set()
    }
    for line in text.splitlines():
        line_str = line.strip()
        if re.search(r'(?:선행|의존|사전|선결|종속|선행작업)', line_str):
            for m in re.findall(r'TASK-\d{3}[a-zA-Z0-9_\-]*', line_str):
                if m != current_task_id:
                    deps["depends_on"].add(m)
        elif re.search(r'(?:대체|개선|후속|supersede)', line_str):
            for m in re.findall(r'TASK-\d{3}[a-zA-Z0-9_\-]*', line_str):
                if m != current_task_id:
                    deps["supersedes"].add(m)

    all_tasks = set(re.findall(r'TASK-\d{3}[a-zA-Z0-9_\-]*', text))
    for t in all_tasks:
        if t != current_task_id and t not in deps["depends_on"] and t not in deps["supersedes"]:
            deps["related_to"].add(t)

    return deps

def extract_symbols_from_source(file_path: Path, relative_path: str) -> tuple[list[dict], list[dict]]:
    """[2단계] 소스 코드(TS/JS/Py)에서 함수, 클래스, 인터페이스, API 엔드포인트 및 호출 관계 추출"""
    entities = []
    relations = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return entities, relations

    # 1. Functions & Methods
    for m in re.finditer(r'(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\(([^)]*)\)', content):
        line_no = content[:m.start()].count('\n') + 1
        name = m.group(1)
        sig = f"function {name}({m.group(2).strip()})"
        entities.append({"type": "function", "name": name, "file": relative_path, "line": line_no, "sig": sig[:150]})

    for m in re.finditer(r'(?:export\s+)?const\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*(?::\s*[^=]+)?\s*=>', content):
        line_no = content[:m.start()].count('\n') + 1
        name = m.group(1)
        sig = f"const {name} = ({m.group(2).strip()}) =>"
        entities.append({"type": "function", "name": name, "file": relative_path, "line": line_no, "sig": sig[:150]})

    for m in re.finditer(r'def\s+([a-zA-Z0-9_]+)\s*\(([^)]*)\):', content):
        line_no = content[:m.start()].count('\n') + 1
        name = m.group(1)
        sig = f"def {name}({m.group(2).strip()}):"
        entities.append({"type": "function", "name": name, "file": relative_path, "line": line_no, "sig": sig[:150]})

    # 2. Classes & Interfaces & Types
    for m in re.finditer(r'(?:export\s+)?class\s+([a-zA-Z0-9_$]+)(?:\s+extends\s+([a-zA-Z0-9_$]+))?', content):
        line_no = content[:m.start()].count('\n') + 1
        name = m.group(1)
        base = m.group(2)
        sig = f"class {name}" + (f" extends {base}" if base else "")
        entities.append({"type": "class", "name": name, "file": relative_path, "line": line_no, "sig": sig})
        if base:
            relations.append({"source": name, "type": "extends", "target": base, "file": relative_path})

    for m in re.finditer(r'(?:export\s+)?interface\s+([a-zA-Z0-9_$]+)', content):
        line_no = content[:m.start()].count('\n') + 1
        name = m.group(1)
        entities.append({"type": "interface", "name": name, "file": relative_path, "line": line_no, "sig": f"interface {name}"})

    for m in re.finditer(r'(?:export\s+)?type\s+([a-zA-Z0-9_$]+)\s*=', content):
        line_no = content[:m.start()].count('\n') + 1
        name = m.group(1)
        entities.append({"type": "type", "name": name, "file": relative_path, "line": line_no, "sig": f"type {name}"})

    # 3. API Endpoints
    for m in re.finditer(r'(?:app|router)\.(get|post|put|delete|patch)\(\s*[\"\']([^\"\']+)[\"\']', content):
        line_no = content[:m.start()].count('\n') + 1
        method = m.group(1).upper()
        route = m.group(2)
        name = f"{method} {route}"
        entities.append({"type": "endpoint", "name": name, "file": relative_path, "line": line_no, "sig": name})

    # 4. Imports relations
    for m in re.finditer(r'import\s+(?:\{([^}]+)\}|([a-zA-Z0-9_$]+))\s+from\s+[\"\']([^\"\']+)[\"\']', content):
        imported = []
        if m.group(1):
            imported = [s.strip().split(' as ')[0].strip() for s in m.group(1).split(',') if s.strip()]
        elif m.group(2):
            imported = [m.group(2).strip()]
        mod = m.group(3)
        for sym in imported:
            relations.append({"source": relative_path, "type": "imports", "target": sym, "file": mod})

    return entities, relations

def chunk_markdown(content: str) -> list[tuple[str, str]]:
    """마크다운을 헤더 단위로 지능형 분할"""
    lines = content.splitlines()
    chunks: list[tuple[str, str]] = []
    current_headers = {1: "", 2: "", 3: "", 4: ""}
    current_lines: list[str] = []
    
    def get_current_header_path():
        parts = [current_headers[lvl] for lvl in (1, 2, 3, 4) if current_headers[lvl]]
        return " > ".join(parts) if parts else "Overview"
    
    for line in lines:
        header_match = re.match(r'^(#{1,4})\s+(.+)$', line)
        if header_match:
            if current_lines:
                body = "\n".join(current_lines).strip()
                if body:
                    chunks.append((get_current_header_path(), body))
                current_lines = []
            
            level = len(header_match.group(1))
            title = header_match.group(2).strip()
            current_headers[level] = title
            for l in range(level + 1, 5):
                current_headers[l] = ""
        else:
            current_lines.append(line)
            
    if current_lines:
        body = "\n".join(current_lines).strip()
        if body:
            chunks.append((get_current_header_path(), body))
            
    return chunks

def index_projects(target_project_id: str | None = None):
    print(f"[*] Initializing Memory Database: {DB_PATH}")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    init_db(conn)
    cursor = conn.cursor()
    
    print(f"[*] Loading Embedding Model: {MODEL_NAME}")
    embed_model = TextEmbedding(MODEL_NAME)
    
    # 색인 대상 프로젝트 목록 결정
    if target_project_id:
        proj_dirs = [PROJECTS_DIR / target_project_id]
        print(f"[*] Scoped index for project: '{target_project_id}'")
        cursor.execute("DELETE FROM task_chunks WHERE project_id = ?", (target_project_id,))
        cursor.execute("DELETE FROM task_chunks_fts WHERE project_id = ?", (target_project_id,))
        cursor.execute("DELETE FROM task_relations WHERE project_id = ?", (target_project_id,))
        cursor.execute("DELETE FROM tasks WHERE project_id = ?", (target_project_id,))
        cursor.execute("DELETE FROM code_entities WHERE project_id = ?", (target_project_id,))
        cursor.execute("DELETE FROM code_relations WHERE project_id = ?", (target_project_id,))
    else:
        proj_dirs = [d for d in PROJECTS_DIR.iterdir() if d.is_dir() and d.name != "template"]
        print(f"[*] Full re-index across {len(proj_dirs)} projects")
        cursor.execute("DELETE FROM task_chunks")
        cursor.execute("DELETE FROM task_chunks_fts")
        cursor.execute("DELETE FROM task_relations")
        cursor.execute("DELETE FROM tasks")
        cursor.execute("DELETE FROM code_entities")
        cursor.execute("DELETE FROM code_relations")
    conn.commit()
    
    all_chunks_to_embed = []
    chunk_meta_list = []
    project_stats = {}
    
    for pdir in proj_dirs:
        if not pdir.exists() or not pdir.is_dir():
            continue
        project_id = pdir.name
        target_src_root = get_project_target_path(project_id)
        tasks_dir = pdir / "tasks"
        if not tasks_dir.exists():
            continue
            
        task_dirs = sorted([d for d in tasks_dir.iterdir() if d.is_dir() and d.name.startswith("TASK-")])
        project_stats[project_id] = len(task_dirs)
        
        project_known_symbols = set()
        
        for tdir in task_dirs:
            task_id = tdir.name
            status_file = tdir / "status.json"
            
            title = task_id
            status = "UNKNOWN"
            owner = ""
            priority = ""
            level = 1
            created_at = ""
            updated_at = ""
            completed_at = ""
            sdata = {}
            
            if status_file.exists():
                try:
                    with open(status_file, "r", encoding="utf-8") as f:
                        sdata = json.load(f)
                        task_id = sdata.get("task_id", task_id)
                        title = sdata.get("title", task_id)
                        status = sdata.get("status", "UNKNOWN")
                        owner = sdata.get("owner", "")
                        priority = sdata.get("priority", "")
                        level = sdata.get("level", 1)
                        created_at = sdata.get("created_at", "")
                        updated_at = sdata.get("updated_at", "")
                        completed_at = sdata.get("completed_at", "")
                        
                        for agent in sdata.get("assigned_agents", []):
                            cursor.execute(
                                """INSERT OR IGNORE INTO task_relations 
                                   (project_id, task_id, relation_type, target) VALUES (?, ?, ?, ?)""",
                                (project_id, task_id, "assigned_agent", agent)
                            )
                        for art in sdata.get("artifacts", []):
                            cursor.execute(
                                """INSERT OR IGNORE INTO task_relations 
                                   (project_id, task_id, relation_type, target) VALUES (?, ?, ?, ?)""",
                                (project_id, task_id, "artifact", art)
                            )
                            
                        # 1단계: status.json 의존/선행 태스크 등록
                        for dep in sdata.get("depends_on", []):
                            if isinstance(dep, str) and dep != task_id:
                                cursor.execute(
                                    """INSERT OR IGNORE INTO task_relations 
                                       (project_id, task_id, relation_type, target) VALUES (?, ?, ?, ?)""",
                                    (project_id, task_id, "depends_on", dep)
                                )
                        for sup in sdata.get("supersedes", []):
                            if isinstance(sup, str) and sup != task_id:
                                cursor.execute(
                                    """INSERT OR IGNORE INTO task_relations 
                                       (project_id, task_id, relation_type, target) VALUES (?, ?, ?, ?)""",
                                    (project_id, task_id, "supersedes", sup)
                                )
                        if sdata.get("parent_task"):
                            cursor.execute(
                                """INSERT OR IGNORE INTO task_relations 
                                   (project_id, task_id, relation_type, target) VALUES (?, ?, ?, ?)""",
                                (project_id, task_id, "subtask_of", sdata["parent_task"])
                            )
                except Exception as e:
                    print(f"[!] Warning reading {status_file}: {e}")
                    
            cursor.execute(
                """INSERT OR REPLACE INTO tasks 
                   (project_id, task_id, title, status, owner, priority, level, created_at, updated_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (project_id, task_id, title, status, owner, priority, level, created_at, updated_at, completed_at)
            )
            
            # 마크다운 파일 색인 및 엔티티/의존성 추출
            md_files = list(tdir.glob("*.md"))
            task_full_text = ""
            for md_file in md_files:
                file_name = md_file.name
                try:
                    with open(md_file, "r", encoding="utf-8") as f:
                        text = f.read()
                        task_full_text += "\n" + text
                except Exception:
                    continue
                    
                referenced_files = extract_file_paths(text)
                for rf in referenced_files:
                    cursor.execute(
                        """INSERT OR IGNORE INTO task_relations 
                           (project_id, task_id, relation_type, target) VALUES (?, ?, ?, ?)""",
                        (project_id, task_id, "modified_file", rf)
                    )
                    
                    # 2단계: 실제 소스 코드 파일에서 코드 심볼/엔티티 그래프 추출
                    abs_src = target_src_root / rf
                    if abs_src.exists() and abs_src.is_file():
                        symbols, code_rels = extract_symbols_from_source(abs_src, rf)
                        for sym in symbols:
                            cursor.execute(
                                """INSERT OR REPLACE INTO code_entities 
                                   (project_id, entity_type, name, file_path, line_number, signature)
                                   VALUES (?, ?, ?, ?, ?, ?)""",
                                (project_id, sym["type"], sym["name"], sym["file"], sym["line"], sym["sig"])
                            )
                            project_known_symbols.add(sym["name"])
                        for cr in code_rels:
                            cursor.execute(
                                """INSERT OR IGNORE INTO code_relations
                                   (project_id, source_name, relation_type, target_name, file_path)
                                   VALUES (?, ?, ?, ?, ?)""",
                                (project_id, cr["source"], cr["type"], cr["target"], cr["file"])
                            )
                    
                file_chunks = chunk_markdown(text)
                for header_path, body in file_chunks:
                    embed_text = f"[{project_id} > {task_id} > {file_name} > {header_path}]\n{body}"
                    all_chunks_to_embed.append(embed_text)
                    chunk_meta_list.append((project_id, task_id, file_name, header_path, body))

            # 1단계: 텍스트 기반 Multi-hop 태스크 인과 관계 추출
            extracted_deps = extract_task_dependencies(task_full_text, task_id)
            for dep in extracted_deps["depends_on"]:
                cursor.execute(
                    """INSERT OR IGNORE INTO task_relations 
                       (project_id, task_id, relation_type, target) VALUES (?, ?, ?, ?)""",
                    (project_id, task_id, "depends_on", dep)
                )
            for sup in extracted_deps["supersedes"]:
                cursor.execute(
                    """INSERT OR IGNORE INTO task_relations 
                       (project_id, task_id, relation_type, target) VALUES (?, ?, ?, ?)""",
                    (project_id, task_id, "supersedes", sup)
                )
            for rel in extracted_deps["related_to"]:
                cursor.execute(
                    """INSERT OR IGNORE INTO task_relations 
                       (project_id, task_id, relation_type, target) VALUES (?, ?, ?, ?)""",
                    (project_id, task_id, "related_to", rel)
                )

            # 2단계: 태스크가 언급/수정한 코드 심볼 연결 (touches_symbol)
            for sym_name in project_known_symbols:
                if len(sym_name) >= 4 and (f"`{sym_name}`" in task_full_text or f" {sym_name}(" in task_full_text):
                    cursor.execute(
                        """INSERT OR IGNORE INTO task_relations 
                           (project_id, task_id, relation_type, target) VALUES (?, ?, ?, ?)""",
                        (project_id, task_id, "touches_symbol", sym_name)
                    )
                    
    print(f"[*] Generating embeddings for {len(all_chunks_to_embed)} chunks...")
    if all_chunks_to_embed:
        embeddings = list(embed_model.embed(all_chunks_to_embed))
        print("[*] Inserting chunks and vectors into SQLite...")
        for (project_id, task_id, file_name, header_path, body), vec in zip(chunk_meta_list, embeddings):
            vec_bytes = np.array(vec, dtype=np.float32).tobytes()
            cursor.execute(
                """INSERT INTO task_chunks 
                   (project_id, task_id, file_name, header_path, content, embedding)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (project_id, task_id, file_name, header_path, body, vec_bytes)
            )
            chunk_id = cursor.lastrowid
            cursor.execute(
                """INSERT INTO task_chunks_fts 
                   (chunk_id, project_id, task_id, file_name, header_path, content)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (chunk_id, project_id, task_id, file_name, header_path, body)
            )
            
    conn.commit()
    
    cursor.execute("SELECT COUNT(*) FROM tasks")
    total_tasks = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM task_chunks")
    total_chunks = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM task_relations")
    total_relations = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM code_entities")
    total_code_entities = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM code_relations")
    total_code_relations = cursor.fetchone()[0]

    # 관계 유형별 통계
    cursor.execute("SELECT relation_type, COUNT(*) FROM task_relations GROUP BY relation_type ORDER BY COUNT(*) DESC")
    rel_type_counts = cursor.fetchall()
    
    # 엔티티 유형별 통계
    cursor.execute("SELECT entity_type, COUNT(*) FROM code_entities GROUP BY entity_type ORDER BY COUNT(*) DESC")
    entity_type_counts = cursor.fetchall()
    
    print("\n" + "="*60)
    print("✅ Multi-Project Vector & Knowledge Graph Indexing Complete!")
    print("="*60)
    for pid, count in project_stats.items():
        print(f" • Project [{pid}]: {count} tasks")
    print(f" • Tasks Indexed:         {total_tasks}")
    print(f" • Chunks & Vectors:      {total_chunks}")
    print(f" • Task Relations (Graph): {total_relations}")
    for r_type, c_cnt in rel_type_counts:
        print(f"    - {r_type:<15}: {c_cnt}")
    print(f" • Code Entities (Nodes):  {total_code_entities}")
    for e_type, e_cnt in entity_type_counts:
        print(f"    - {e_type:<15}: {e_cnt}")
    print(f" • Code Relations (Edges): {total_code_relations}")
    print(f" • Database Path:          {DB_PATH}")
    print("="*60 + "\n")
    
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-Project Agent Memory Indexer (Vector + Graph)")
    parser.add_argument("--project", help="Index only a specific project ID")
    args = parser.parse_args()
    
    index_projects(target_project_id=args.project)
