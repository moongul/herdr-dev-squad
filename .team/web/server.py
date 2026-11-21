#!/usr/bin/env python3
"""
Herdr Agent Swarm Command Deck - Backend Web Server
- REST API for live agent monitoring, Controller IPC dispatch, Kanban, and SQLite Memory
- Serves the Command Deck Web UI
"""

import os
import sys
import json
import time
import re
import sqlite3
import subprocess
import threading
from pathlib import Path
from typing import Optional
import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # Dev workspace root
TEAM_DIR = BASE_DIR / ".team"
WEB_DIR = TEAM_DIR / "web"
PROJECTS_DIR = TEAM_DIR / "projects"
ACTIVE_FILE = TEAM_DIR / "active_project"
TASKS_FILE = TEAM_DIR / "TASKS.md"
MEMORY_DB = TEAM_DIR / "memory" / "memory.db"
SWITCH_SCRIPT = TEAM_DIR / "scripts" / "switch-project.sh"

HERDR_SESSION = "Dev"
PORT = 8080

ROLE_METADATA = {
    "controller": {
        "name": "controller",
        "title": "@controller",
        "role": "Orchestrator & Workflow Dispatcher",
        "tab": "Dev1",
        "model": "Gemini 3.8 Flash",
        "color": "#06b6d4",
        "icon": "fa-sitemap",
        "desc": "사용자 지시 수렴, 태스크 등록, 에이전트 간 위임 및 상태 관리"
    },
    "planner": {
        "name": "planner",
        "title": "@planner",
        "role": "Task Graph & RCA Troubleshooter",
        "tab": "Dev1",
        "model": "Gemini 4 Neon",
        "color": "#3b82f6",
        "icon": "fa-brain",
        "desc": "요구사항 분석, WBS 분해, 결함 근본원인(RCA) 분석 및 수정계획 수립"
    },
    "architector": {
        "name": "architector",
        "title": "@architector",
        "role": "API Contract Keeper & System Architect",
        "tab": "Dev2",
        "model": "Muse Spark 1.3 (pi)",
        "color": "#8b5cf6",
        "icon": "fa-layer-group",
        "desc": "API/타입 계약(Contract) 선제 확정, 모듈 분할 및 리팩토링 설계"
    },
    "designer": {
        "name": "designer",
        "title": "@designer",
        "role": "Design System & UI/UX Specialist",
        "tab": "Dev2",
        "model": "Gemini 4 Argon",
        "color": "#ec4899",
        "icon": "fa-palette",
        "desc": "UI/UX 화면 명세, 시맨틱 레이아웃 및 디자인 토큰 가이드"
    },
    "frontend": {
        "name": "frontend",
        "title": "@frontend",
        "role": "Client App & Interactive UI Engineer",
        "tab": "Dev3",
        "model": "Gemini 4 Hydrogen",
        "color": "#10b981",
        "icon": "fa-desktop",
        "desc": "브라우저 UI, 캔버스 렌더러, 클라이언트 상태, API 연결"
    },
    "backend": {
        "name": "backend",
        "title": "@backend",
        "role": "Core Engine & API Service Engineer",
        "tab": "Dev3",
        "model": "Gemini 4 Hydrogen",
        "color": "#14b8a6",
        "icon": "fa-server",
        "desc": "API 엔드포인트, 도메인 비즈니스 로직, 검증기, 데이터 모델"
    },
    "reviewer": {
        "name": "reviewer",
        "title": "@reviewer",
        "role": "Independent Code & Security Auditor",
        "tab": "Dev4",
        "model": "Muse Spark 1.3 (pi)",
        "color": "#f59e0b",
        "icon": "fa-code-compare",
        "desc": "독립 코드 리뷰, API 계약 준수 검토, 결함 및 취약점 감사"
    },
    "qa": {
        "name": "qa",
        "title": "@qa",
        "role": "Autonomous E2E & Browser Test Engine",
        "tab": "Dev4",
        "model": "Muse Spark 1.3 (pi)",
        "color": "#f43f5e",
        "icon": "fa-vial-circle-check",
        "desc": "E2E 브라우저 테스트, 실측 렌더링 검증, 회귀 테스트 판정"
    }
}

ORDERED_ROLES = list(ROLE_METADATA.keys())

_AGENTS_CFG = BASE_DIR / ".team" / "agents.json"
if _AGENTS_CFG.exists():
    try:
        _custom = json.loads(_AGENTS_CFG.read_text(encoding="utf-8"))
        for _r, _ov in (_custom.get("roles") or {}).items():
            if _r in ROLE_METADATA and isinstance(_ov, dict):
                if _ov.get("model"):
                    ROLE_METADATA[_r]["model"] = _ov["model"]
                if _ov.get("tab_label"):
                    ROLE_METADATA[_r]["tab"] = _ov["tab_label"]
    except Exception:
        pass

# ANSI escape sequence remover
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub('', text)

def run_herdr(args: list[str], timeout: int = 4) -> dict | None:
    cmd = ["herdr", "--session", HERDR_SESSION] + args
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=timeout)
        return json.loads(res.stdout)
    except Exception:
        return None

def run_herdr_raw(args: list[str], timeout: int = 4) -> str:
    cmd = ["herdr", "--session", HERDR_SESSION] + args
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.stdout
    except Exception as e:
        return f"Error executing herdr: {e}"

def read_agent_terminal(role_name: str, lines: int = 100, pane_id: str = "") -> str:
    """에이전트 터미널 출력 읽기 (이름 유실 시 pane label로 pane_id 폴백 및 자동 이름 복구)"""
    out = run_herdr_raw(["agent", "read", role_name, "--lines", str(lines)], timeout=4)
    if "agent_not_found" in out or not out.strip():
        target_pane = pane_id
        if not target_pane:
            pane_list_raw = run_herdr(["pane", "list"])
            if pane_list_raw and "result" in pane_list_raw and "panes" in pane_list_raw["result"]:
                for p in pane_list_raw["result"]["panes"]:
                    if p.get("label") == role_name and p.get("pane_id"):
                        target_pane = p["pane_id"]
                        break
        if target_pane:
            run_herdr(["agent", "rename", target_pane, role_name])
            out = run_herdr_raw(["pane", "read", "--lines", str(lines), target_pane], timeout=4)
    return out

def get_active_project() -> str:
    if ACTIVE_FILE.exists():
        try:
            val = ACTIVE_FILE.read_text(encoding="utf-8").strip()
            if val:
                return val
        except Exception:
            pass
    return "default"

def get_project_list() -> list[str]:
    if not PROJECTS_DIR.exists():
        return ["default"]
    projs = []
    for p in sorted(PROJECTS_DIR.iterdir()):
        if p.is_dir() and p.name != "template":
            projs.append(p.name)
    return projs or ["default"]

def get_token_metrics(role_name: str, agent_type: str, session_id: str) -> str:
    if not session_id:
        return "세션 없음"
    try:
        if agent_type == "agy":
            t_file = Path.home() / ".gemini" / "antigravity-cli" / "brain" / session_id / ".system_generated" / "logs" / "transcript.jsonl"
            if t_file.exists():
                with open(t_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                for line in reversed(lines[-40:]):
                    try:
                        d = json.loads(line)
                        if "input_tokens" in d and "cache_read_tokens" in d:
                            in_tok = d.get("input_tokens", 0)
                            cache_tok = d.get("cache_read_tokens", 0)
                            out_tok = d.get("output_tokens", 0)
                            total_ctx_k = (in_tok + cache_tok) // 1000
                            return f"{total_ctx_k}k ctx (out: {out_tok})"
                    except Exception:
                        pass
            return f"세션: {session_id[:8]}..."
        elif agent_type == "qoder":
            qoder_slug = "-" + str(BASE_DIR).lstrip("/").replace("/", "-")
            q_file = Path.home() / ".qoder" / "projects" / qoder_slug / f"{session_id}.jsonl"
            if q_file.exists():
                with open(q_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                for line in reversed(lines[-100:]):
                    try:
                        d = json.loads(line)
                        u = d.get("message", {}).get("usage", {})
                        if "context_usage_ratio" in u:
                            ratio = float(u["context_usage_ratio"])
                            remain_pct = max(0.0, (1.0 - ratio) * 100)
                            return f"잔여 {remain_pct:.1f}% ({ratio*100:.1f}% 사용)"
                    except Exception:
                        pass
            return f"세션: {session_id[:8]}..."
        elif agent_type == "claude":
            claude_slug = "-" + str(BASE_DIR).lstrip("/").replace("/", "-")
            c_file = Path.home() / ".claude" / "projects" / claude_slug / f"{session_id}.jsonl"
            if c_file.exists():
                with open(c_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                for line in reversed(lines[-30:]):
                    try:
                        d = json.loads(line)
                        if d.get("type") == "cost-state":
                            cost = d.get("totalCostUSD", 0.0)
                            return f"${cost:.3f}"
                    except Exception:
                        pass
            return f"세션: {session_id[:8]}..."
        elif agent_type == "pi":
            p_file = Path(session_id) if session_id.startswith("/") else None
            if not p_file or not p_file.exists():
                matches = list(Path.home().glob(f".pi/agent/sessions/*/*{session_id}*.jsonl"))
                p_file = matches[0] if matches else None
            if p_file and p_file.exists():
                with open(p_file, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                for line in reversed(lines[-40:]):
                    try:
                        d = json.loads(line)
                        u = d.get("message", {}).get("usage", {})
                        if isinstance(u, dict) and u.get("totalTokens"):
                            tok_k = int(u["totalTokens"]) // 1000
                            return f"사용 {tok_k}k tok"
                    except Exception:
                        pass
            return f"세션: {Path(session_id).stem[-8:]}"
    except Exception:
        pass
    return f"세션: {session_id[:8]}..."

def get_agents_data() -> list[dict]:
    """Herdr agent list + pane list + terminal output + token metrics 종합"""
    agent_list_raw = run_herdr(["agent", "list"])
    pane_list_raw = run_herdr(["pane", "list"])

    live_by_name = {}
    if agent_list_raw and "result" in agent_list_raw and "agents" in agent_list_raw["result"]:
        for a in agent_list_raw["result"]["agents"]:
            name = a.get("name")
            if name:
                live_by_name[name] = a

    panes_by_label = {}
    if pane_list_raw and "result" in pane_list_raw and "panes" in pane_list_raw["result"]:
        for p in pane_list_raw["result"]["panes"]:
            lbl = p.get("label")
            if lbl:
                panes_by_label[lbl] = p

    # 저장된 세션 파일
    cur_proj = get_active_project()
    sess_file = PROJECTS_DIR / cur_proj / "sessions.json"
    saved_sessions = {}
    if sess_file.exists():
        try:
            saved_sessions = json.loads(sess_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    results = []
    for role in ORDERED_ROLES:
        meta = ROLE_CONFIGS = ROLE_METADATA[role]
        live = live_by_name.get(role, {})
        pane = panes_by_label.get(role, {})
        sess = saved_sessions.get(role, {})

        pane_id = live.get("pane_id") or pane.get("pane_id") or sess.get("pane_id") or "w?:p?"
        status = live.get("agent_status") or pane.get("agent_status") or "idle"
        cli_agent = live.get("agent") or pane.get("agent") or sess.get("agent_type") or "agy"

        # 세션 ID 및 토큰 지표
        sess_val = (live.get("agent_session") or {}).get("value") or sess.get("session_id") or ""
        metrics = get_token_metrics(role, cli_agent, sess_val)

        # 최근 터미널 출력 15줄 (생각 / 현재 활동 추출)
        recent_text = read_agent_terminal(role, lines=18, pane_id=pane_id)
        clean_text = strip_ansi(recent_text).strip()
        last_lines = [l.strip() for l in clean_text.splitlines() if l.strip()]

        # Thought / Current task 추출
        thought = ""
        current_task = "대기 중 (Standby)"
        for line in reversed(last_lines[-10:]):
            if "Thought for" in line or "생각" in line:
                thought = line
                break
        if not thought and last_lines:
            thought = last_lines[-1][:120]

        for line in reversed(last_lines):
            if "TASK-" in line:
                m_task = re.search(r'(TASK-\d+[-a-z0-9]*)', line)
                if m_task:
                    current_task = m_task.group(1)
                    break
            elif "작업 지시" in line or "Phase" in line:
                current_task = line[:60]
                break

        results.append({
            "id": role,
            "name": f"@{role}",
            "role": meta["role"],
            "title": meta["title"],
            "desc": meta["desc"],
            "tab": meta["tab"],
            "pane_id": pane_id,
            "model": meta["model"],
            "cli": cli_agent,
            "status": status.upper(),
            "color": meta["color"],
            "icon": meta["icon"],
            "metrics": metrics,
            "session_id": sess_val,
            "thought": thought or f"{role} 에이전트 대기 중...",
            "current_task": current_task,
            "last_output": clean_text
        })

    return results

def get_tasks_kanban() -> dict:
    """TASKS.md 및 .team/tasks/*/status.json을 실시간 통합 파싱하여 4단계 칸반 반환 (최신순 정렬)"""
    kanban = {
        "queued": [],
        "in_progress": [],
        "review_qa": [],
        "done": []
    }

    tasks_by_id = {}

    # 1. TASKS.md 파싱
    if TASKS_FILE.exists():
        try:
            content = TASKS_FILE.read_text(encoding="utf-8")
            lines = content.splitlines()
            for line in lines:
                if not line.startswith("| TASK-"):
                    continue
                cols = [c.strip() for c in line.split("|")[1:-1]]
                if len(cols) < 5:
                    continue

                task_id = cols[0]
                title = cols[1]
                status = cols[2].upper()
                assignee = cols[3]
                waiting_on = cols[4]

                tasks_by_id[task_id] = {
                    "id": task_id,
                    "title": title,
                    "status": status,
                    "assignee": assignee,
                    "waiting_on": waiting_on,
                    "updated_at": "",
                    "artifacts": []
                }
        except Exception as e:
            print(f"Error parsing TASKS.md: {e}")

    # 2. .team/tasks/*/status.json 실시간 오버레이 (새로 생성되거나 실행 중인 태스크 상태 우선 반영)
    tasks_dir = TEAM_DIR / "tasks"
    if tasks_dir.exists():
        for s_file in tasks_dir.glob("*/status.json"):
            try:
                s_data = json.loads(s_file.read_text(encoding="utf-8"))
                tid = s_data.get("task_id")
                if not tid:
                    continue
                raw_st = (s_data.get("status") or "QUEUED").upper()
                if tid in tasks_by_id:
                    tasks_by_id[tid]["status"] = raw_st
                    if s_data.get("owner"):
                        tasks_by_id[tid]["assignee"] = s_data["owner"]
                    tasks_by_id[tid]["updated_at"] = s_data.get("updated_at") or ""
                    tasks_by_id[tid]["artifacts"] = s_data.get("artifacts") or []
                    if s_data.get("title"):
                        tasks_by_id[tid]["title"] = s_data["title"]
                else:
                    tasks_by_id[tid] = {
                        "id": tid,
                        "title": s_data.get("title", tid),
                        "status": raw_st,
                        "assignee": s_data.get("owner", "Controller"),
                        "waiting_on": s_data.get("pending_action") or "—",
                        "updated_at": s_data.get("updated_at") or "",
                        "artifacts": s_data.get("artifacts") or []
                    }
            except Exception:
                pass

    # 2.5. 태스크 디렉토리 내 산출물(*.md) 자동 탐색 보강
    tasks_dir = TEAM_DIR / "tasks"
    if tasks_dir.exists():
        for task_id, t_item in tasks_by_id.items():
            if not t_item.get("artifacts"):
                for tdir in tasks_dir.glob(f"*{task_id}*"):
                    if tdir.is_dir():
                        mds = [f.name for f in tdir.glob("*.md")]
                        if mds:
                            t_item["artifacts"] = sorted(mds)
                            break

    # 3. 4단계 칸반 분류
    for task_item in tasks_by_id.values():
        status = task_item["status"]
        if "COMPLETED" in status or "DONE" in status or "CANCELLED" in status:
            kanban["done"].append(task_item)
        elif "REVIEW" in status or "QA" in status:
            kanban["review_qa"].append(task_item)
        elif "IN_PROGRESS" in status or "WORKING" in status or "EXEC" in status or "DEV" in status:
            kanban["in_progress"].append(task_item)
        else:
            kanban["queued"].append(task_item)

    # 4. 정렬: 최신 태스크 번호가 큰 것부터 최상단에 노출
    def _task_sort_key(t):
        m = re.search(r"TASK-(\d+)", t["id"])
        num = int(m.group(1)) if m else 0
        return (num, t.get("updated_at", ""))

    kanban["done"].sort(key=_task_sort_key, reverse=True)
    kanban["review_qa"].sort(key=_task_sort_key, reverse=True)
    kanban["in_progress"].sort(key=_task_sort_key, reverse=True)
    kanban["queued"].sort(key=_task_sort_key, reverse=True)

    return kanban

ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"}
IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".bmp": "image/bmp",
    ".ico": "image/x-icon",
}

def resolve_image_path(path_str: str) -> Optional[Path]:
    """로컬 이미지 경로(file:///... 또는 절대/상대 경로)를 안전하게 검증 후 반환"""
    if not path_str:
        return None
    clean = path_str.strip()
    if clean.startswith("file://"):
        clean = clean[7:]
    if ".." in clean.split("/"):
        return None

    p = Path(clean)
    if not p.is_absolute():
        p = (BASE_DIR / clean)

    try:
        resolved = p.resolve()
    except Exception:
        return None

    if not resolved.exists() or not resolved.is_file():
        return None

    if resolved.suffix.lower() not in ALLOWED_IMAGE_EXTS:
        return None

    allowed_roots = [
        (Path.home() / ".gemini" / "antigravity-cli" / "brain").resolve(),
        BASE_DIR.resolve(),
        BASE_DIR.parent.resolve(),
        Path("/tmp").resolve(),
    ]
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue

    return None

def resolve_artifact_path(path_str: str, task_id: str = "") -> Optional[Path]:
    """태스크 산출물 경로를 안전하게 탐색하여 실체 경로 반환 (디렉토리 탈출 방지 적용)"""
    if not path_str:
        return None

    clean = path_str.strip().lstrip("/")
    if ".." in clean.split("/"):
        return None

    candidates: list[Path] = []
    candidates.append((BASE_DIR / clean).resolve())

    if task_id:
        candidates.append((TEAM_DIR / "tasks" / task_id / clean).resolve())
        candidates.append((TEAM_DIR / "tasks" / task_id / Path(clean).name).resolve())
        tasks_dir = TEAM_DIR / "tasks"
        if tasks_dir.exists():
            for tdir in tasks_dir.glob(f"*{task_id}*"):
                if tdir.is_dir():
                    candidates.append((tdir / clean).resolve())
                    candidates.append((tdir / Path(clean).name).resolve())

    if "TASK-" in clean:
        parts = clean.split("/")
        for part in parts:
            if part.startswith("TASK-"):
                tasks_dir = TEAM_DIR / "tasks"
                if tasks_dir.exists():
                    for tdir in tasks_dir.glob(f"*{part}*"):
                        if tdir.is_dir():
                            candidates.append((tdir / Path(clean).name).resolve())

    allowed_roots = [BASE_DIR.resolve(), TEAM_DIR.resolve()]
    try:
        act_p = get_active_project()
        if act_p:
            allowed_roots.append((TEAM_DIR / "projects" / act_p).resolve())
    except Exception:
        pass

    for c in candidates:
        if c.exists() and c.is_file():
            for root_boundary in allowed_roots:
                try:
                    c.relative_to(root_boundary)
                    return c
                except ValueError:
                    continue

    return None

def get_memory_stats() -> dict:
    """memory.db SQLite에서 현재 활성 프로젝트 기준 통계, 최근 청크 및 실시간 지식 그래프 토폴로지 추출"""
    cur_proj = get_active_project()
    stats = {
        "project_id": cur_proj,
        "total_chunks": 0,
        "total_relations": 0,
        "total_tasks": 0,
        "recent_chunks": [],
        "relations": [],
        "access_stats": {
            "total_queries": 0,
            "by_agent": [],
            "recent_queries": []
        },
        "graph": {
            "nodes": [],
            "links": []
        }
    }

    if not MEMORY_DB.exists():
        return stats

    try:
        conn = sqlite3.connect(f"file:{MEMORY_DB}?mode=ro", uri=True, timeout=5.0)
        conn.execute("PRAGMA busy_timeout=5000;")
        cur = conn.cursor()

        # 청크 수 (현재 활성 프로젝트 스코프)
        cur.execute("SELECT COUNT(*) FROM task_chunks WHERE project_id = ?", (cur_proj,))
        stats["total_chunks"] = cur.fetchone()[0]

        # 관계 수 (현재 활성 프로젝트 스코프)
        cur.execute("SELECT COUNT(*) FROM task_relations WHERE project_id = ?", (cur_proj,))
        rel_cnt = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM code_relations WHERE project_id = ?", (cur_proj,))
        stats["total_relations"] = rel_cnt + cur.fetchone()[0]

        # 태스크 수 (현재 활성 프로젝트 스코프)
        cur.execute("SELECT COUNT(*) FROM tasks WHERE project_id = ?", (cur_proj,))
        stats["total_tasks"] = cur.fetchone()[0]

        # 최근 청크 15개 (현재 활성 프로젝트 스코프)
        cur.execute("""
            SELECT task_id, header_path, content 
            FROM task_chunks 
            WHERE project_id = ?
            ORDER BY chunk_id DESC LIMIT 15
        """, (cur_proj,))
        for row in cur.fetchall():
            stats["recent_chunks"].append({
                "task_id": row[0],
                "header": row[1] or "Section",
                "preview": (row[2] or "").strip()[:180]
            })

        # 토폴로지용 그래프 관계 샘플 35개 (현재 활성 프로젝트 스코프)
        cur.execute("""
            SELECT task_id, target, relation_type 
            FROM task_relations 
            WHERE project_id = ?
            ORDER BY id DESC LIMIT 35
        """, (cur_proj,))
        raw_relations = cur.fetchall()
        for row in raw_relations:
            stats["relations"].append({
                "source": row[0],
                "target": row[1],
                "type": row[2]
            })

        # 실시간 Force-Directed 2D 지식 그래프 노드 및 엣지 생성
        nodes_map = {
            "session": {"id": "session", "label": f"Dev:{cur_proj}", "type": "session", "color": "#06b6d4", "r": 13},
            "controller": {"id": "controller", "label": "@controller", "type": "agent", "color": "#06b6d4", "r": 10},
            "planner": {"id": "planner", "label": "@planner", "type": "agent", "color": "#a855f7", "r": 10},
            "frontend": {"id": "frontend", "label": "@frontend", "type": "agent", "color": "#3b82f6", "r": 10},
            "backend": {"id": "backend", "label": "@backend", "type": "agent", "color": "#10b981", "r": 10},
            "qa": {"id": "qa", "label": "@qa", "type": "agent", "color": "#ec4899", "r": 10},
        }

        links = [
            {"source": "session", "target": "controller", "type": "leads"},
            {"source": "controller", "target": "planner", "type": "delegates"},
            {"source": "controller", "target": "frontend", "type": "dispatches"},
            {"source": "controller", "target": "backend", "type": "dispatches"},
            {"source": "controller", "target": "qa", "type": "validates"},
        ]

        for task_id, target, rel_type in raw_relations:
            # 1. Task Node
            m = re.search(r"TASK-(\d+)", task_id)
            short_task = f"TASK-{m.group(1)}" if m else task_id[:10]
            if task_id not in nodes_map:
                nodes_map[task_id] = {
                    "id": task_id,
                    "label": short_task,
                    "type": "task",
                    "color": "#a855f7",
                    "r": 8
                }
                # Assign to agent
                if "frontend" in task_id or "ui" in task_id:
                    links.append({"source": "frontend", "target": task_id, "type": "assigned"})
                elif "backend" in task_id or "api" in task_id:
                    links.append({"source": "backend", "target": task_id, "type": "assigned"})
                else:
                    links.append({"source": "controller", "target": task_id, "type": "assigned"})

            # 2. Target Node (Symbol, Artifact, or Concept)
            if target not in nodes_map:
                if target.endswith(".md") or target.endswith(".ts") or target.endswith(".tsx") or "/" in target:
                    lbl = target.split("/")[-1]
                    nodes_map[target] = {
                        "id": target,
                        "label": lbl[:16],
                        "type": "artifact",
                        "color": "#10b981",
                        "r": 6
                    }
                elif target.startswith("TASK-"):
                    m2 = re.search(r"TASK-(\d+)", target)
                    lbl2 = f"TASK-{m2.group(1)}" if m2 else target[:10]
                    nodes_map[target] = {
                        "id": target,
                        "label": lbl2,
                        "type": "task",
                        "color": "#a855f7",
                        "r": 7
                    }
                else:
                    nodes_map[target] = {
                        "id": target,
                        "label": target[:16],
                        "type": "concept",
                        "color": "#f59e0b",
                        "r": 6
                    }

            links.append({"source": task_id, "target": target, "type": rel_type})

        stats["graph"]["nodes"] = list(nodes_map.values())
        stats["graph"]["links"] = links

        # 에이전트별 메모리 조회 감사 로그 통계 (현재 활성 프로젝트 스코프)
        try:
            cur.execute("SELECT COUNT(*) FROM memory_access_logs WHERE project_id = ?", (cur_proj,))
            stats["access_stats"]["total_queries"] = cur.fetchone()[0]

            cur.execute("""
                SELECT agent_name, COUNT(*) as cnt, MAX(accessed_at) as last_at
                FROM memory_access_logs
                WHERE project_id = ?
                GROUP BY agent_name
                ORDER BY cnt DESC, last_at DESC
            """, (cur_proj,))
            stats["access_stats"]["by_agent"] = [
                {"agent": r[0], "count": r[1], "last_at": r[2]}
                for r in cur.fetchall()
            ]

            cur.execute("""
                SELECT accessed_at, project_id, agent_name, query_text, target_file, result_count, duration_ms
                FROM memory_access_logs
                WHERE project_id = ?
                ORDER BY log_id DESC LIMIT 10
            """, (cur_proj,))
            stats["access_stats"]["recent_queries"] = [
                {
                    "accessed_at": r[0],
                    "project_id": r[1],
                    "agent": r[2],
                    "query": r[3] or r[4] or "",
                    "result_count": r[5],
                    "duration_ms": r[6]
                }
                for r in cur.fetchall()
            ]
        except sqlite3.OperationalError:
            pass

        conn.close()
    except Exception as e:
        print(f"Error reading memory DB: {e}")

    return stats

# --------------------------------------------------------------------------
# Controller Background Prompt Execution & History
# --------------------------------------------------------------------------
CONTROLLER_HISTORY = []
CONTROLLER_LOCK = threading.Lock()

def clean_terminal_output(raw_text: str) -> tuple[str, str]:
    """터미널 출력에서 크롬을 제거하고 (답변 본문, 생각)을 분리 추출"""
    clean = strip_ansi(raw_text)
    lines = clean.splitlines()

    thought = ""
    response_lines = []

    for line in lines:
        s = line.strip()
        if "Thought for" in s or "생각" in s:
            thought = s
            continue
        if s.startswith("● Ran") or s.startswith("● Explored") or s.startswith("● Edited") or s.startswith("● Created"):
            continue
        if s.startswith("? for shortcuts") or "Gemini 3.8 Flash" in s or "YOLO Shift+Tab" in s or "esc to cancel" in s:
            continue
        if s.startswith("─") or s == ">" or s.startswith("> "):
            continue
        response_lines.append(line)

    return "\n".join(response_lines).strip(), thought

def get_controller_transcript_history(limit: int = 15) -> list[dict]:
    """Controller의 transcript.jsonl에서 최근 대화 내역 추출 (마크다운 원본 및 사고과정 포함)"""
    cur_proj = get_active_project()
    sess_file = PROJECTS_DIR / cur_proj / "sessions.json"
    session_id = None
    if sess_file.exists():
        try:
            d = json.loads(sess_file.read_text(encoding="utf-8"))
            session_id = d.get("controller", {}).get("session_id")
        except Exception:
            pass

    if not session_id:
        return []

    t_file = Path.home() / ".gemini" / "antigravity-cli" / "brain" / session_id / ".system_generated" / "logs" / "transcript.jsonl"
    if not t_file.exists():
        return []

    entries = []
    try:
        with open(t_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        current_prompt = None
        current_time = ""
        current_responses = []
        current_thinking = []

        for line in lines:
            try:
                data = json.loads(line)
            except Exception:
                continue

            t_type = data.get("type")
            if t_type == "USER_INPUT":
                if current_prompt is not None and (current_responses or current_thinking):
                    entries.append({
                        "id": f"turn_{len(entries)}",
                        "timestamp": current_time,
                        "operator_prompt": current_prompt,
                        "status": "DONE",
                        "thought": "\n\n".join(t for t in current_thinking if t).strip(),
                        "response": "\n\n".join(r for r in current_responses if r).strip()
                    })

                raw_content = data.get("content", "") or ""
                m = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", raw_content, re.DOTALL)
                current_prompt = m.group(1).strip() if m else raw_content.strip()

                created_at = data.get("created_at", "")
                if created_at and "T" in created_at:
                    try:
                        dt_part = created_at.split(".")[0].rstrip("Z")
                        if "Z" in created_at or "+00:00" in created_at:
                            from datetime import datetime, timezone, timedelta
                            utc_dt = datetime.fromisoformat(dt_part).replace(tzinfo=timezone.utc)
                            kst_dt = utc_dt.astimezone(timezone(timedelta(hours=9)))
                            current_time = kst_dt.strftime("%H:%M:%S")
                        else:
                            current_time = created_at.split("T")[1][:8]
                    except Exception:
                        current_time = created_at.split("T")[1][:8]
                else:
                    current_time = time.strftime("%H:%M:%S")

                current_responses = []
                current_thinking = []

            elif t_type == "PLANNER_RESPONSE":
                c = data.get("content")
                th = data.get("thinking")
                if c and c.strip():
                    current_responses.append(c.strip())
                if th and th.strip():
                    current_thinking.append(th.strip())

        if current_prompt is not None and (current_responses or current_thinking):
            entries.append({
                "id": f"turn_{len(entries)}",
                "timestamp": current_time,
                "operator_prompt": current_prompt,
                "status": "DONE",
                "thought": "\n\n".join(t for t in current_thinking if t).strip(),
                "response": "\n\n".join(r for r in current_responses if r).strip()
            })

    except Exception as e:
        print(f"Error reading transcript: {e}")

    return entries[-limit:]

def dispatch_controller_prompt(prompt_text: str):
    """Controller에게 herdr agent prompt 전송 및 응답 추적"""
    timestamp = time.strftime("%H:%M:%S")
    entry = {
        "id": f"msg_{int(time.time()*1000)}",
        "timestamp": timestamp,
        "operator_prompt": prompt_text,
        "status": "WORKING",
        "thought": "",
        "response": "",
        "actions": []
    }

    with CONTROLLER_LOCK:
        CONTROLLER_HISTORY.append(entry)

    def _worker():
        try:
            # 1. Herdr prompt 전송 (비동기 완료 대기 최대 180초)
            subprocess.run(
                ["herdr", "--session", HERDR_SESSION, "agent", "prompt", "controller", prompt_text, "--wait", "--timeout", "180000"],
                capture_output=True, text=True, timeout=190
            )
        except Exception as e:
            print(f"Error in controller prompt dispatch: {e}")

        # 2. 결과 읽기: transcript.jsonl 우선, 폴백으로 터미널 파싱
        time.sleep(1.0)
        history = get_controller_transcript_history(limit=5)
        clean_p = prompt_text.strip()
        matched = None
        for h in reversed(history):
            if clean_p in h["operator_prompt"] or h["operator_prompt"] in clean_p:
                matched = h
                break

        if matched:
            resp_text = matched["response"]
            th_text = matched["thought"]
        else:
            output = run_herdr_raw(["agent", "read", "controller", "--lines", "60"], timeout=4)
            resp_text, th_text = clean_terminal_output(output)

        with CONTROLLER_LOCK:
            entry["status"] = "DONE"
            entry["response"] = resp_text or "작업이 접수되어 처리가 완료되었습니다."
            entry["thought"] = th_text

    threading.Thread(target=_worker, daemon=True).start()

# --------------------------------------------------------------------------
# HTTP Request Handler
# --------------------------------------------------------------------------
class SwarmAPIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            return super().do_GET()

        # REST API Routes
        if path == "/api/status":
            act_proj = get_active_project()
            projs = get_project_list()
            agents = get_agents_data()
            working_cnt = sum(1 for a in agents if a["status"] in ["WORKING", "RUNNING", "GENERATING"])
            mem = get_memory_stats()
            kanban = get_tasks_kanban()
            total_tasks = len(kanban["queued"]) + len(kanban["in_progress"]) + len(kanban["review_qa"]) + len(kanban["done"])
            done_tasks = len(kanban["done"])
            pct = int((done_tasks / total_tasks * 100)) if total_tasks > 0 else 100

            self.send_json({
                "session": HERDR_SESSION,
                "active_project": act_proj,
                "projects": projs,
                "agents_count": len(agents),
                "active_agents": working_cnt,
                "task_progress": {
                    "total": total_tasks,
                    "completed": done_tasks,
                    "queued": len(kanban["queued"]),
                    "in_progress": len(kanban["in_progress"]),
                    "review_qa": len(kanban["review_qa"]),
                    "percent": pct
                },
                "memory": {
                    "chunks": mem["total_chunks"],
                    "relations": mem["total_relations"]
                }
            })
            return

        elif path == "/api/agents":
            agents = get_agents_data()
            self.send_json({"agents": agents})
            return

        elif path.startswith("/api/agent/") and path.endswith("/terminal"):
            role_name = path.split("/")[3]
            lines = 100
            qs = parse_qs(parsed.query)
            if "lines" in qs:
                try:
                    lines = int(qs["lines"][0])
                except Exception:
                    pass
            out = read_agent_terminal(role_name, lines=lines)
            self.send_json({
                "agent": role_name,
                "output": strip_ansi(out)
            })
            return

        elif path == "/api/tasks":
            kanban = get_tasks_kanban()
            self.send_json(kanban)
            return

        elif path == "/api/image":
            qs = parse_qs(parsed.query)
            img_path = qs.get("path", [""])[0]
            resolved_img = resolve_image_path(img_path)
            if not resolved_img:
                self.send_error(404, "Image not found or access denied")
                return

            try:
                data = resolved_img.read_bytes()
                mime = IMAGE_MIME_TYPES.get(resolved_img.suffix.lower(), "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_error(500, f"Failed to serve image: {e}")
            return

        elif path == "/api/artifact":
            qs = parse_qs(parsed.query)
            art_path = qs.get("path", [""])[0]
            task_id = qs.get("task_id", [""])[0]

            if not art_path:
                self.send_json({"success": False, "error": "Missing artifact path parameter"}, status=400)
                return

            resolved_file = resolve_artifact_path(art_path, task_id)
            if not resolved_file or not resolved_file.is_file():
                self.send_json({"success": False, "error": f"Artifact file not found: {art_path}"}, status=404)
                return

            try:
                content_text = resolved_file.read_text(encoding="utf-8", errors="replace")
                stat = resolved_file.stat()
                mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                size = stat.st_size
                if size < 1024:
                    size_fmt = f"{size} B"
                elif size < 1024 * 1024:
                    size_fmt = f"{size / 1024:.1f} KB"
                else:
                    size_fmt = f"{size / (1024 * 1024):.2f} MB"

                rel_path = ""
                try:
                    rel_path = str(resolved_file.relative_to(BASE_DIR))
                except Exception:
                    rel_path = resolved_file.name

                self.send_json({
                    "success": True,
                    "filename": resolved_file.name,
                    "path": rel_path,
                    "task_id": task_id,
                    "size": size,
                    "size_formatted": size_fmt,
                    "updated_at": mtime,
                    "ext": resolved_file.suffix.lstrip(".").lower(),
                    "content": content_text
                })
            except Exception as e:
                self.send_json({"success": False, "error": f"Failed to read artifact: {str(e)}"}, status=500)
            return

        elif path == "/api/memory":
            mem = get_memory_stats()
            self.send_json(mem)
            return

        elif path == "/api/controller/history":
            history = get_controller_transcript_history(limit=15)
            with CONTROLLER_LOCK:
                for active in CONTROLLER_HISTORY:
                    if active.get("status") == "WORKING":
                        history.append(active)
            self.send_json({"history": history})
            return

        # Default static file serving
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            req_data = json.loads(post_body)
        except Exception:
            req_data = {}

        if path == "/api/controller/prompt":
            prompt_text = req_data.get("prompt", "").strip()
            if not prompt_text:
                self.send_json({"error": "Empty prompt"}, status=400)
                return

            dispatch_controller_prompt(prompt_text)
            self.send_json({
                "status": "DISPATCHED",
                "message": f"Prompt successfully forwarded to @controller in Herdr Dev session.",
                "prompt": prompt_text
            })
            return

        elif path == "/api/project/switch":
            target_proj = req_data.get("project", "").strip()
            if not target_proj:
                self.send_json({"error": "Missing project"}, status=400)
                return

            def _switch():
                subprocess.run([str(SWITCH_SCRIPT), target_proj, "--keep-controller"], capture_output=True)

            threading.Thread(target=_switch, daemon=True).start()
            self.send_json({
                "status": "SWITCHING",
                "message": f"Switching active project to '{target_proj}'..."
            })
            return

        self.send_json({"error": "Not Found"}, status=404)

def run_server(port: int = PORT):
    server_address = ("", port)
    httpd = ThreadingHTTPServer(server_address, SwarmAPIHandler)
    print(f"==================================================")
    print(f"🚀 Herdr Agent Swarm Command Deck WebUI Running!")
    print(f"🔗 Local URL:  http://localhost:{port}")
    print(f"📁 Root Dir:   {WEB_DIR}")
    print(f"⚡ Session:    {HERDR_SESSION} (8 Active Agents)")
    print(f"==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Stopping WebUI server...")
        httpd.server_close()

if __name__ == "__main__":
    p = PORT
    if len(sys.argv) >= 2:
        try:
            p = int(sys.argv[1])
        except Exception:
            pass
    run_server(p)
