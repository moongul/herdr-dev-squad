# /// script
# dependencies = [
#     "fastembed",
#     "numpy",
# ]
# ///

import sys
import os
import time
import re
import argparse
import json
import sqlite3
import numpy as np
from pathlib import Path
from fastembed import TextEmbedding

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # Dev workspace root
DB_PATH = BASE_DIR / ".team" / "memory" / "memory.db"
ACTIVE_FILE = BASE_DIR / ".team" / "active_project"
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

def get_active_project() -> str:
    if ACTIVE_FILE.exists():
        try:
            with open(ACTIVE_FILE, "r", encoding="utf-8") as f:
                val = f.read().strip()
                if val:
                    return val
        except Exception:
            pass
    return "default"

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a, axis=1)
    norm_b = np.linalg.norm(b)
    return dot / (norm_a * norm_b + 1e-9)

def find_multi_hop_chains(conn: sqlite3.Connection, project_id: str | None, task_ids: list[str], max_depth: int = 3) -> dict:
    """[1단계] SQLite WITH RECURSIVE 재귀 질의로 선행 의존 태스크와 후행 영향 태스크 인과 체인 횡단"""
    cursor = conn.cursor()
    chains = {
        "predecessors": [],
        "successors": []
    }
    if not task_ids:
        return chains

    placeholders = ",".join(["?"] * len(task_ids))
    
    # 1. Upstream Recursive Chain (선행 작업 및 의존 관계)
    upstream_sql = f"""
    WITH RECURSIVE upstream_chain(project_id, task_id, depth, relation_type, parent_task, path) AS (
        SELECT project_id, task_id, 0, 'origin', '', task_id
        FROM tasks
        WHERE task_id IN ({placeholders})
        {"AND project_id = ?" if project_id else ""}
        
        UNION
        
        SELECT tr.project_id, tr.target, uc.depth + 1, tr.relation_type, uc.task_id, uc.path || ' ➜ (' || tr.relation_type || ') ➜ ' || tr.target
        FROM task_relations tr
        JOIN upstream_chain uc ON tr.project_id = uc.project_id AND tr.task_id = uc.task_id
        WHERE tr.relation_type IN ('depends_on', 'subtask_of', 'supersedes', 'related_to')
          AND uc.depth < {max_depth}
          AND uc.path NOT LIKE '%' || tr.target || '%'
    )
    SELECT DISTINCT uc.project_id, uc.task_id, uc.depth, uc.relation_type, uc.path, t.title, t.status
    FROM upstream_chain uc
    LEFT JOIN tasks t ON uc.project_id = t.project_id AND uc.task_id = t.task_id
    WHERE uc.depth > 0
    ORDER BY uc.depth ASC;
    """
    params = list(task_ids)
    if project_id:
        params.append(project_id)
    try:
        cursor.execute(upstream_sql, params)
        for r in cursor.fetchall():
            chains["predecessors"].append({
                "project_id": r[0], "task_id": r[1], "depth": r[2], "relation": r[3],
                "path": r[4], "title": r[5] or r[1], "status": r[6] or "UNKNOWN"
            })
    except Exception:
        pass

    # 2. Downstream Recursive Chain (후행 작업 및 변경 영향도)
    downstream_sql = f"""
    WITH RECURSIVE downstream_chain(project_id, task_id, depth, relation_type, child_task, path) AS (
        SELECT project_id, task_id, 0, 'origin', '', task_id
        FROM tasks
        WHERE task_id IN ({placeholders})
        {"AND project_id = ?" if project_id else ""}
        
        UNION
        
        SELECT tr.project_id, tr.task_id, dc.depth + 1, tr.relation_type, dc.task_id, dc.path || ' ➜ [impacted_by] ➜ ' || tr.task_id
        FROM task_relations tr
        JOIN downstream_chain dc ON tr.project_id = dc.project_id AND (tr.target = dc.task_id OR dc.task_id LIKE tr.target || '%' OR tr.target LIKE dc.task_id || '%')
        WHERE tr.relation_type IN ('depends_on', 'subtask_of', 'supersedes', 'related_to')
          AND dc.depth < {max_depth}
          AND dc.path NOT LIKE '%' || tr.task_id || '%'
    )
    SELECT DISTINCT dc.project_id, dc.task_id, dc.depth, dc.relation_type, dc.path, t.title, t.status
    FROM downstream_chain dc
    LEFT JOIN tasks t ON dc.project_id = t.project_id AND dc.task_id = t.task_id
    WHERE dc.depth > 0
    ORDER BY dc.depth ASC;
    """
    try:
        cursor.execute(downstream_sql, params)
        for r in cursor.fetchall():
            chains["successors"].append({
                "project_id": r[0], "task_id": r[1], "depth": r[2], "relation": r[3],
                "path": r[4], "title": r[5] or r[1], "status": r[6] or "UNKNOWN"
            })
    except Exception:
        pass

    return chains

def search_code_symbols(conn: sqlite3.Connection, project_id: str | None, symbol_name: str) -> list[dict]:
    """[2단계] 코드 엔티티(함수, 클래스, API) 및 수정 태스크 역추적 조회"""
    cursor = conn.cursor()
    symbols = []
    
    q = "SELECT entity_id, project_id, entity_type, name, file_path, line_number, signature FROM code_entities WHERE name LIKE ?"
    params = [f"%{symbol_name}%"]
    if project_id:
        q += " AND project_id = ?"
        params.append(project_id)
    q += " ORDER BY CASE WHEN name = ? THEN 1 WHEN name LIKE ? THEN 2 ELSE 3 END LIMIT 10"
    params.extend([symbol_name, f"{symbol_name}%"])
    
    try:
        cursor.execute(q, params)
        for r in cursor.fetchall():
            eid, pid, etype, name, fpath, line, sig = r
            
            cursor.execute(
                "SELECT DISTINCT task_id FROM task_relations WHERE project_id = ? AND relation_type = 'touches_symbol' AND target = ?",
                (pid, name)
            )
            tasks = [row[0] for row in cursor.fetchall()]
            
            cursor.execute(
                "SELECT relation_type, target_name, file_path FROM code_relations WHERE project_id = ? AND source_name = ? LIMIT 5",
                (pid, name)
            )
            out_rels = [{"type": row[0], "target": row[1], "file": row[2]} for row in cursor.fetchall()]
            
            cursor.execute(
                "SELECT source_name, relation_type, file_path FROM code_relations WHERE project_id = ? AND target_name = ? LIMIT 5",
                (pid, name)
            )
            in_rels = [{"source": row[0], "type": row[1], "file": row[2]} for row in cursor.fetchall()]

            symbols.append({
                "project_id": pid,
                "name": name,
                "type": etype,
                "file": fpath,
                "line": line,
                "signature": sig,
                "touched_by_tasks": tasks,
                "out_relations": out_rels,
                "in_relations": in_rels
            })
    except Exception:
        pass
        
    return symbols

def log_memory_access(
    conn: sqlite3.Connection,
    project_id: str,
    agent_name: str,
    query_text: str,
    target_file: str | None,
    target_symbol: str | None,
    task_id: str | None,
    result_count: int,
    duration_ms: int,
):
    """에이전트의 memory.db 조회 이력을 memory_access_logs 테이블에 기록"""
    try:
        conn.execute("""
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
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_access_agent ON memory_access_logs(agent_name, accessed_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_access_time ON memory_access_logs(accessed_at DESC)")
        clean_agent = (agent_name or "unknown").strip().lower().lstrip("@") or "unknown"
        conn.execute(
            """
            INSERT INTO memory_access_logs
                (project_id, agent_name, query_text, target_file, target_symbol, task_id, result_count, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id or "ALL",
                clean_agent,
                (query_text or "")[:300],
                target_file,
                target_symbol,
                task_id,
                int(result_count),
                int(duration_ms),
            ),
        )
        conn.commit()
    except Exception:
        pass

def search_memory(
    query: str,
    project_id: str | None = None,
    target_file: str | None = None,
    target_symbol: str | None = None,
    task_id: str | None = None,
    top_k: int = 5,
    dense_weight: float = 0.6,
    fts_weight: float = 0.4,
    agent_name: str = "unknown"
):
    if not DB_PATH.exists():
        return {"error": "Memory database not found. Please run indexer.py first."}

    started_at = time.monotonic()
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    cursor = conn.cursor()
    
    # 프로젝트 스코프 결정
    active_proj = get_active_project()
    scoped_project = None
    if project_id and project_id.lower() == "all":
        scoped_project = None  # 전체 검색
    elif project_id:
        scoped_project = project_id.lower()
    else:
        scoped_project = active_proj  # 기본값: 현재 활성 프로젝트
        
    # [2단계] 심볼 검색 우선 확인
    symbol_entities = []
    symbol_matched_tasks = set()
    lookup_symbol = target_symbol or (query.strip().split()[0] if len(query.strip().split()) == 1 and re.match(r'^[a-zA-Z0-9_$]+$', query.strip()) else None)
    if lookup_symbol:
        symbol_entities = search_code_symbols(conn, scoped_project, lookup_symbol)
        for s in symbol_entities:
            for tid in s["touched_by_tasks"]:
                symbol_matched_tasks.add((s["project_id"], tid))

    # [1단계] 태스크 ID 확장 매칭 (접두사/부분일치 지원)
    task_matched_ids = set()
    if task_id:
        cursor.execute(
            "SELECT DISTINCT task_id FROM tasks WHERE (task_id = ? OR task_id LIKE ?)" + (" AND project_id = ?" if scoped_project else ""),
            [task_id, f"{task_id}%"] + ([scoped_project] if scoped_project else [])
        )
        task_matched_ids = {r[0] for r in cursor.fetchall()}
        if not task_matched_ids:
            cursor.execute(
                "SELECT DISTINCT task_id FROM tasks WHERE task_id LIKE ?" + (" AND project_id = ?" if scoped_project else ""),
                [f"%{task_id}%"] + ([scoped_project] if scoped_project else [])
            )
            task_matched_ids = {r[0] for r in cursor.fetchall()}
        if not task_matched_ids:
            task_matched_ids.add(task_id)

    # [1단계] 파일 기반 필터링 (Lightweight Graph 조회)
    file_matched_tasks = set()
    if target_file:
        q = "SELECT DISTINCT project_id, task_id FROM task_relations WHERE relation_type = 'modified_file' AND target LIKE ?"
        params = [f"%{target_file}%"]
        if scoped_project:
            q += " AND project_id = ?"
            params.append(scoped_project)
        cursor.execute(q, params)
        file_matched_tasks = {(row[0], row[1]) for row in cursor.fetchall()}
        
    # Dense Vector 검색
    embed_model = TextEmbedding(MODEL_NAME)
    q_vec = list(embed_model.embed([query]))[0]
    q_vec = np.array(q_vec, dtype=np.float32)
    
    q = "SELECT chunk_id, project_id, task_id, file_name, header_path, content, embedding FROM task_chunks"
    params = []
    if scoped_project:
        q += " WHERE project_id = ?"
        params.append(scoped_project)
    cursor.execute(q, params)
    all_chunks = cursor.fetchall()
    
    chunk_ids = []
    chunk_meta = {}
    vec_list = []
    
    for r in all_chunks:
        cid, pid, tid, fname, hpath, body, emb_bytes = r
        if task_id and (tid not in task_matched_ids and not any(m in tid for m in task_matched_ids)):
            continue
        if target_file and file_matched_tasks and ((pid, tid) not in file_matched_tasks):
            continue
            
        chunk_ids.append(cid)
        chunk_meta[cid] = {
            "chunk_id": cid,
            "project_id": pid,
            "task_id": tid,
            "file_name": fname,
            "header_path": hpath,
            "content": body
        }
        vec_list.append(np.frombuffer(emb_bytes, dtype=np.float32))
        
    if not vec_list:
        # 청크가 없어도 심볼 또는 태스크 인과 체인이 있으면 계산하여 반환
        seed_tasks = list(task_matched_ids) if task_id else [t for p, t in symbol_matched_tasks]
        chains = find_multi_hop_chains(conn, scoped_project, seed_tasks[:4], max_depth=3) if seed_tasks else {"predecessors": [], "successors": []}
        conn.close()
        return {
            "query": query, 
            "project": scoped_project or "ALL", 
            "total_found": 0, 
            "symbol_entities": symbol_entities,
            "multi_hop_chains": chains,
            "results": []
        }
        
    vec_matrix = np.vstack(vec_list)
    dense_scores = cosine_similarity(vec_matrix, q_vec)
    
    dense_rankings = {}
    for rank, idx in enumerate(np.argsort(-dense_scores)):
        cid = chunk_ids[idx]
        dense_rankings[cid] = (rank + 1, float(dense_scores[idx]))
        
    # FTS5 키워드 검색
    fts_rankings = {}
    fts_clean_query = re_clean_fts(query)
    if fts_clean_query:
        try:
            fts_sql = "SELECT chunk_id, rank FROM task_chunks_fts WHERE task_chunks_fts MATCH ?"
            fts_params = [fts_clean_query]
            if scoped_project:
                fts_sql += " AND project_id = ?"
                fts_params.append(scoped_project)
            fts_sql += " ORDER BY rank LIMIT 100"
            
            cursor.execute(fts_sql, fts_params)
            for rank, row in enumerate(cursor.fetchall()):
                cid = row[0]
                if cid in chunk_meta:
                    fts_rankings[cid] = (rank + 1, float(row[1]))
        except Exception:
            pass
            
    # RRF 결합 (심볼 매칭 태스크에는 가산점 부여)
    rrf_scores = {}
    for cid in chunk_meta.keys():
        score = 0.0
        meta = chunk_meta[cid]
        if cid in dense_rankings:
            d_rank, d_sim = dense_rankings[cid]
            score += dense_weight * (1.0 / (60.0 + d_rank))
        if cid in fts_rankings:
            f_rank, _ = fts_rankings[cid]
            score += fts_weight * (1.0 / (60.0 + f_rank))
        if symbol_matched_tasks and (meta["project_id"], meta["task_id"]) in symbol_matched_tasks:
            score += 0.02  # 심볼 매칭 보너스 가중치
        rrf_scores[cid] = score
        
    sorted_cids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)[:top_k]
    
    matched_task_ids = []
    results = []
    for cid in sorted_cids:
        meta = chunk_meta[cid]
        pid = meta["project_id"]
        tid = meta["task_id"]
        if tid not in matched_task_ids:
            matched_task_ids.append(tid)
        
        cursor.execute(
            "SELECT target FROM task_relations WHERE project_id = ? AND task_id = ? AND relation_type = 'modified_file'",
            (pid, tid)
        )
        related_files = [row[0] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT target FROM task_relations WHERE project_id = ? AND task_id = ? AND relation_type = 'touches_symbol'",
            (pid, tid)
        )
        touched_symbols = [row[0] for row in cursor.fetchall()]
        
        results.append({
            "project_id": pid,
            "task_id": tid,
            "header": meta["header_path"],
            "file": meta["file_name"],
            "score": round(rrf_scores[cid], 5),
            "related_files": related_files[:5],
            "touched_symbols": touched_symbols[:5],
            "content": meta["content"]
        })

    # [1단계] 매칭된 상위 태스크들의 Multi-hop 인과 관계망 횡단 (선행/후행 체인)
    seed_tasks = list(matched_task_ids[:4])
    if task_id:
        for tid in task_matched_ids:
            if tid not in seed_tasks:
                seed_tasks.append(tid)
    if symbol_matched_tasks:
        for p, tid in symbol_matched_tasks:
            if tid not in seed_tasks:
                seed_tasks.append(tid)
    multi_hop_chains = find_multi_hop_chains(conn, scoped_project, seed_tasks[:4], max_depth=3)

    duration_ms = int((time.monotonic() - started_at) * 1000)
    log_memory_access(
        conn=conn,
        project_id=scoped_project or "ALL",
        agent_name=agent_name,
        query_text=query,
        target_file=target_file,
        target_symbol=target_symbol,
        task_id=task_id,
        result_count=len(results),
        duration_ms=duration_ms,
    )

    conn.close()
    return {
        "query": query, 
        "project": scoped_project or "ALL", 
        "total_found": len(results), 
        "symbol_entities": symbol_entities,
        "multi_hop_chains": multi_hop_chains,
        "results": results
    }

def re_clean_fts(text: str) -> str:
    words = [w.strip() for w in text.replace('"', ' ').replace("'", ' ').split() if len(w.strip()) > 1]
    return " OR ".join(words) if words else ""

def format_terminal(output: dict):
    scope_str = output.get("project", "ALL")
    query_str = output.get("query", "")
    symbols = output.get("symbol_entities", [])
    chains = output.get("multi_hop_chains", {})
    results = output.get("results", [])

    print(f"\n🧠 Knowledge Graph & Memory Search (Project: {scope_str}) for: \"{query_str}\"\n" + "="*75)

    # 1. [2단계] 코드 엔티티 그래프 카드 출력
    if symbols:
        print("🧬 CODE ENTITY KNOWLEDGE GRAPH:")
        for sym in symbols[:3]:
            print(f"  • [{sym['type'].upper()}] {sym['name']}")
            print(f"    - 정의 위치: {sym['file']}:{sym['line']}")
            if sym.get('signature'):
                print(f"    - 시그니처: {sym['signature']}")
            if sym.get('touched_by_tasks'):
                print(f"    - 연관 태스크: {', '.join(sym['touched_by_tasks'])}")
            if sym.get('out_relations'):
                out_strs = [f"{r['type']} ➜ {r['target']}" for r in sym['out_relations']]
                print(f"    - 호출/임포트: {', '.join(out_strs)}")
            if sym.get('in_relations'):
                in_strs = [f"{r['source']} ({r['type']})" for r in sym['in_relations']]
                print(f"    - 참조처: {', '.join(in_strs)}")
        print(" " + "-"*73)

    # 2. [1단계] Multi-hop 태스크 인과 체인 출력
    preds = chains.get("predecessors", [])
    succs = chains.get("successors", [])
    if preds or succs:
        print("🔗 MULTI-HOP TASK CAUSAL CHAIN:")
        if preds:
            print("  [선행 및 의존 체인 (Upstream)]: ")
            seen_paths = set()
            for p in preds:
                if p["path"] not in seen_paths:
                    seen_paths.add(p["path"])
                    print(f"    ▲ {p['path']} [{p['status']}] - {p['title']}")
        if succs:
            print("  [후행 및 영향 체인 (Downstream)]: ")
            seen_paths = set()
            for s in succs:
                if s["path"] not in seen_paths:
                    seen_paths.add(s["path"])
                    print(f"    ▼ {s['path']} [{s['status']}] - {s['title']}")
        print(" " + "-"*73)

    # 3. RAG 컨텍스트 청크 결과 출력
    if not results:
        print(f"  [!] 본문 청크 검색 결과가 없습니다.\n")
        return

    print(f"📚 RELEVANT MEMORY CHUNKS ({len(results)} found):")
    for i, res in enumerate(results, 1):
        print(f"[{i}] [{res['project_id'].upper()}] Task: {res['task_id']} | File: {res['file']} (RRF Score: {res['score']})")
        print(f"    Context: {res['header']}")
        if res.get('related_files'):
            print(f"    Modified Files: {', '.join(res['related_files'])}")
        if res.get('touched_symbols'):
            print(f"    Touched Symbols: {', '.join(res['touched_symbols'])}")
        print(f"    " + "-"*50)
        snippet = res['content'].strip()
        lines = snippet.splitlines()
        if len(lines) > 8:
            snippet = "\n".join(lines[:8]) + "\n    ... (truncated)"
        indented = "\n".join("    " + line for line in snippet.splitlines())
        print(indented)
        print("="*75)
    print()

def main():
    parser = argparse.ArgumentParser(description="Multi-Project Vector & Knowledge Graph Search Tool")
    parser.add_argument("query", nargs="?", default="", help="Search query (natural language or keywords)")
    parser.add_argument("--project", help="Filter by Project ID (or 'all'). Defaults to active project.")
    parser.add_argument("--file", help="Filter by modified source file name")
    parser.add_argument("--symbol", help="Search code entities (functions, classes, endpoints) and reverse-track related tasks")
    parser.add_argument("--task", help="Filter by specific Task ID")
    parser.add_argument("--top-k", type=int, default=3, help="Number of results to return")
    parser.add_argument("--agent", default=os.environ.get("HERDR_AGENT") or os.environ.get("AGENT_NAME") or "unknown", help="Calling agent name (e.g. controller, backend, frontend)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    
    args = parser.parse_args()

    search_query = args.query or args.symbol or args.file or args.task or ""
    if not search_query:
        parser.print_help()
        sys.exit(1)
    
    res = search_memory(
        query=search_query,
        project_id=args.project,
        target_file=args.file,
        target_symbol=args.symbol,
        task_id=args.task,
        top_k=args.top_k,
        agent_name=args.agent
    )
    
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        format_terminal(res)

if __name__ == "__main__":
    main()
