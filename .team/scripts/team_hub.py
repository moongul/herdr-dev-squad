#!/usr/bin/env python3
"""
Herdr Team Project Hub (Interactive Tabbed TUI Dashboard)
- 상단 탭으로 Work 내 프로젝트들을 자유롭게 미리보기(Preview)
- 에이전트 8인의 실시간 상태, 토큰 사용량, 잔여량 실시간 파싱
- 최근 태스크 진행 현황 및 상세 리포트 카드 제공
- [Enter] 단 한 번으로 대상 프로젝트로 즉시 전환 & 세션 복원
"""

import os
import re
import sys
import json
import curses
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # Dev workspace root
PROJECTS_DIR = BASE_DIR / ".team" / "projects"
ACTIVE_FILE = BASE_DIR / ".team" / "active_project"
SWITCH_SCRIPT = BASE_DIR / ".team" / "scripts" / "switch-project.sh"
HERDR_SESSION = "Dev"

ROLE_CONFIGS = {
    "controller": {"type": "agy", "group": "Dev1 (기획)"},
    "planner":    {"type": "agy", "group": "Dev1 (기획)"},
    "architector":{"type": "pi", "group": "Dev2 (설계)"},
    "designer":   {"type": "agy", "group": "Dev2 (설계)"},
    "frontend":   {"type": "agy",   "group": "Dev3 (개발)"},
    "backend":    {"type": "agy",    "group": "Dev3 (개발)"},
    "reviewer":   {"type": "pi", "group": "Dev4 (검증)"},
    "qa":         {"type": "pi", "group": "Dev4 (검증)"},
}

_AGENTS_CFG = BASE_DIR / ".team" / "agents.json"
if _AGENTS_CFG.exists():
    try:
        _custom = json.loads(_AGENTS_CFG.read_text(encoding="utf-8"))
        for _r, _ov in (_custom.get("roles") or {}).items():
            if _r in ROLE_CONFIGS and isinstance(_ov, dict):
                if _ov.get("agent_type"):
                    ROLE_CONFIGS[_r]["type"] = _ov["agent_type"]
                if _ov.get("group"):
                    ROLE_CONFIGS[_r]["group"] = _ov["group"]
    except Exception:
        pass

# -------------------------------------------------------------
# 1. 데이터 수집 함수들
# -------------------------------------------------------------

def get_active_project() -> str:
    if ACTIVE_FILE.exists():
        try:
            return ACTIVE_FILE.read_text(encoding="utf-8").strip() or "default"
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

def get_project_info(project_id: str) -> dict:
    proj_dir = PROJECTS_DIR / project_id
    spec_file = proj_dir / "PROJECT.md"
    
    info = {
        "name": project_id,
        "target_path": str(BASE_DIR.parent / project_id),
        "stack": "TypeScript, React, Node.js",
        "description": ""
    }
    
    if spec_file.exists():
        try:
            content = spec_file.read_text(encoding="utf-8")
            m_path = re.search(r"원본 코드 경로:\s*([^\n]+)", content)
            if m_path:
                info["target_path"] = m_path.group(1).strip()
            m_stack = re.search(r"## 기술 스택\s*\n- ([^\n]+)", content)
            if m_stack:
                info["stack"] = m_stack.group(1).strip()
            m_desc = re.search(r"목적/주 사용자:\s*([^\n]+)", content)
            if m_desc:
                info["description"] = m_desc.group(1).strip()
        except Exception:
            pass
            
    return info

def get_token_metrics(role_name: str, agent_type: str, session_id: str) -> str:
    """각 CLI의 로컬 세션 로그에서 실시간 토큰 및 컨텍스트 잔여량 추출"""
    if not session_id:
        return "세션 없음"
        
    try:
        if agent_type == "agy":
            # agy transcript.jsonl
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
                            out_k = out_tok // 1000
                            return f"📊 {total_ctx_k}k ctx (out: {out_tok})"
                    except Exception:
                        pass
            return f"세션 ID: {session_id[:8]}..."

        elif agent_type == "qoder":
            # qoder jsonl
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
                            return f"🔋 잔여 {remain_pct:.1f}% ({ratio*100:.1f}% 사용)"
                    except Exception:
                        pass
            return f"세션 ID: {session_id[:8]}..."

        elif agent_type == "claude":
            # claude cost-state
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
                            m_usage = d.get("modelUsage", {})
                            in_tok = 0
                            for m in m_usage.values():
                                in_tok += m.get("inputTokens", 0)
                            in_m = in_tok / 1000000.0
                            return f"💰 ${cost:.2f} ({in_m:.2f}M tok)"
                    except Exception:
                        pass
            return f"세션 ID: {session_id[:8]}..."

        elif agent_type == "pi":
            return f"세션 ID: {session_id[:8]}..."

        elif agent_type == "opencode":
            res = subprocess.run(
                ["opencode", "session", "export", session_id],
                capture_output=True,
                text=True,
                timeout=2
            )
            if res.returncode == 0:
                m_in = re.search(r"\"input\":\s*(\d+)", res.stdout)
                m_out = re.search(r"\"output\":\s*(\d+)", res.stdout)
                if m_in and m_out:
                    in_k = int(m_in.group(1)) // 1000
                    out_k = int(m_out.group(1)) // 1000
                    return f"📊 {in_k}k in / {out_k}k out"
            return f"세션 ID: {session_id[:8]}..."

    except Exception:
        pass

    return f"세션 ID: {session_id[:8]}..."

def get_herdr_agent_statuses() -> dict[str, str]:
    """Herdr에서 실시간 에이전트 실행 상태 조회"""
    try:
        res = subprocess.run(
            ["herdr", "--session", HERDR_SESSION, "agent", "list"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if res.returncode == 0:
            data = json.loads(res.stdout)
            status_map = {}
            for ag in data.get("result", {}).get("agents", []):
                name = ag.get("name")
                status = ag.get("agent_status", "unknown")
                if name:
                    status_map[name] = status
            return status_map
    except Exception:
        pass
    return {}

def get_project_tasks(project_id: str) -> list[dict]:
    """해당 프로젝트의 최근 태스크 목록 수집"""
    proj_dir = PROJECTS_DIR / project_id
    tasks_dir = proj_dir / "tasks"
    if not tasks_dir.exists():
        return []
        
    tasks = []
    for tdir in sorted(tasks_dir.iterdir(), reverse=True):
        if not tdir.is_dir() or not tdir.name.startswith("TASK-"):
            continue
        if tdir.name == "TASK-000-template":
            continue
            
        task_info = {
            "id": tdir.name,
            "title": tdir.name,
            "status": "PENDING",
            "level": "Level 2",
            "owner": "Controller",
            "summary": ""
        }
        
        status_file = tdir / "status.json"
        if status_file.exists():
            try:
                sdata = json.loads(status_file.read_text(encoding="utf-8"))
                task_info["status"] = sdata.get("status", "PENDING")
                task_info["level"] = f"Level {sdata.get('level', 2)}"
                task_info["owner"] = sdata.get("owner", "Controller")
            except Exception:
                pass
                
        task_md = tdir / "task.md"
        if task_md.exists():
            try:
                lines = task_md.read_text(encoding="utf-8").splitlines()
                for line in lines:
                    if line.startswith("# "):
                        task_info["title"] = line[2:].strip()
                        break
                    m_title = re.search(r"작업명:\s*([^\n]+)", line)
                    if m_title:
                        task_info["title"] = m_title.group(1).strip()
            except Exception:
                pass
                
        # 최근 요약 추출 (development-report 또는 history)
        rep_file = list(tdir.glob("*-report.md"))
        if rep_file and rep_file[0].exists():
            try:
                r_text = rep_file[0].read_text(encoding="utf-8")
                m_sum = re.search(r"## 1\.\s*개요[^\n]*\n([^\n]+)", r_text) or re.search(r"## 요약[^\n]*\n([^\n]+)", r_text)
                if m_sum:
                    task_info["summary"] = m_sum.group(1).strip()
            except Exception:
                pass
                
        tasks.append(task_info)
        
    return tasks

# -------------------------------------------------------------
# 2. Curses TUI 대시보드 메인 렌더러
# -------------------------------------------------------------

def prompt_new_project_modal(stdscr, existing_projects: list[str]) -> str | None:
    """신규 프로젝트 디렉토리 경로를 입력받는 중앙 curses 모달"""
    max_y, max_x = stdscr.getmaxyx()
    box_w = min(max_x - 6, 76)
    box_h = 13
    start_y = max(1, (max_y - box_h) // 2)
    start_x = max(2, (max_x - box_w) // 2)

    win = curses.newwin(box_h, box_w, start_y, start_x)
    win.keypad(True)

    buf = str(BASE_DIR.parent) + "/"
    err_msg = ""
    confirm_mkdir = False

    def derive_info(raw_path: str):
        cleaned = raw_path.strip().rstrip("/")
        if not cleaned or cleaned in ("~", "/", ".", ".."):
            return "", "", False
        expanded = os.path.expanduser(cleaned)
        p = Path(expanded)
        name = p.name
        if not name or name in (".", ".."):
            return expanded, "", False
        proj_id = re.sub(r"\s+", "-", name.lower())
        return expanded, proj_id, p.is_dir()

    curses.curs_set(1)
    try:
        while True:
            win.erase()
            win.attron(curses.color_pair(1))
            win.box()
            win.attroff(curses.color_pair(1))

            title = " ➕ NEW PROJECT & RESET ALL AGENTS "
            win.addstr(0, max(2, (box_w - len(title)) // 2), title, curses.color_pair(1) | curses.A_BOLD)

            win.addstr(2, 3, "프로젝트 디렉토리 경로를 입력하세요 (마지막 폴더명 = 프로젝트 ID):", curses.A_BOLD)

            # 입력 박스
            field_w = box_w - 6
            display_buf = buf if len(buf) <= field_w - 2 else "…" + buf[-(field_w - 3):]
            win.attron(curses.color_pair(3))
            win.addstr(4, 3, " " * field_w)
            win.addstr(4, 4, display_buf)
            win.attroff(curses.color_pair(3))

            expanded, proj_id, exists = derive_info(buf)
            if proj_id:
                win.addstr(6, 3, f"프로젝트 ID : ", curses.A_DIM)
                win.addstr(6, 17, proj_id, curses.color_pair(1) | curses.A_BOLD)
                if proj_id in existing_projects:
                    win.addstr(7, 3, "상태        : 이미 등록된 프로젝트 (Enter 시 전환)", curses.color_pair(5))
                elif exists:
                    win.addstr(7, 3, "상태        : 기존 디렉토리 확인됨 · 8개 에이전트 초기화 기동", curses.color_pair(4))
                else:
                    win.addstr(7, 3, "상태        : 미존재 경로 · 생성 후 8개 에이전트 초기화 기동", curses.color_pair(5))
            else:
                win.addstr(6, 3, "프로젝트 ID : (경로 끝에 폴더명을 입력해 주세요)", curses.A_DIM)
                win.addstr(7, 3, "예시        : ~/Work/my-new-app 또는 /path/to/my-app", curses.A_DIM)

            if err_msg:
                win.addstr(9, 3, err_msg[:box_w - 6], curses.color_pair(6) | curses.A_BOLD)
            elif confirm_mkdir:
                win.addstr(9, 3, "디렉토리가 없습니다. 새로 생성하고 전환할까요? [y: 생성 / n: 취소]", curses.color_pair(5) | curses.A_BOLD)
            else:
                win.addstr(9, 3, "※ 현재 프로젝트 세션은 자동 저장되며, 신규 프로젝트는 초기화 상태로 시작됩니다.", curses.A_DIM)

            win.addstr(11, 3, "[Enter]: 확인  │  [Ctrl+U]: 지우기  │  [ESC]: 취소", curses.A_DIM)

            # 커서 위치 지정
            cursor_x = min(3 + 1 + len(display_buf), 3 + field_w - 1)
            win.move(4, cursor_x)
            win.refresh()

            try:
                key = win.get_wch()
            except curses.error:
                continue

            if confirm_mkdir:
                if key in ("y", "Y"):
                    return expanded
                confirm_mkdir = False
                err_msg = ""
                continue

            if key in ("\x1b", 27):  # ESC
                return None
            elif key in ("\n", "\r", curses.KEY_ENTER):
                err_msg = ""
                if not proj_id or proj_id == "template":
                    err_msg = "! 올바른 프로젝트 폴더명을 경로 끝에 입력해 주세요."
                    continue
                if exists or proj_id in existing_projects:
                    return expanded
                confirm_mkdir = True
            elif key in ("\x7f", "\b", curses.KEY_BACKSPACE, 127, 8):
                buf = buf[:-1]
                err_msg = ""
            elif key == "\x15":  # Ctrl+U
                buf = ""
                err_msg = ""
            elif isinstance(key, str) and key.isprintable():
                buf += key
                err_msg = ""
    finally:
        curses.curs_set(0)

def run_tui(stdscr):
    curses.curs_set(0)
    curses.use_default_colors()
    stdscr.timeout(1000)  # 1초마다 자동 새로고침
    
    # 색상 초기화
    curses.init_pair(1, curses.COLOR_CYAN, -1)     # Header / Title
    curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLUE) # Active Tab
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE) # Selected Item
    curses.init_pair(4, curses.COLOR_GREEN, -1)    # Success / Idle
    curses.init_pair(5, curses.COLOR_YELLOW, -1)   # Warning / Working
    curses.init_pair(6, curses.COLOR_RED, -1)      # Danger / Blocked
    curses.init_pair(7, curses.COLOR_MAGENTA, -1)  # Special / Completed
    
    projects = get_project_list()
    active_proj = get_active_project()
    
    # 기본 선택 탭: 현재 활성 프로젝트
    tab_idx = 0
    if active_proj in projects:
        tab_idx = projects.index(active_proj)
        
    selected_task_scroll = 0
    switch_target_on_exit = None

    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        
        if max_y < 24 or max_x < 80:
            stdscr.addstr(0, 0, f"터미널 창을 키워주세요 (현재: {max_x}x{max_y}, 최소: 80x24)")
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (ord('q'), 27):
                break
            continue
            
        current_view_proj = projects[tab_idx]
        is_active = (current_view_proj == active_proj)
        proj_info = get_project_info(current_view_proj)
        tasks = get_project_tasks(current_view_proj)
        
        # sessions.json 로드
        sess_file = PROJECTS_DIR / current_view_proj / "sessions.json"
        saved_sessions = {}
        if sess_file.exists():
            try:
                saved_sessions = json.loads(sess_file.read_text(encoding="utf-8"))
            except Exception:
                pass
                
        herdr_statuses = get_herdr_agent_statuses() if is_active else {}

        # ---------------------------------------------------------
        # Header Bar (Top)
        # ---------------------------------------------------------
        title_str = " ⚡ HERDR MULTI-PROJECT & AGENT SQUAD HUB "
        stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(0, (max_x - len(title_str)) // 2, title_str)
        stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
        
        key_hints = "[Tab/←/→]: 탭 전환  │  [Enter]: 전환  │  [n]: 신규 프로젝트  │  [q/ESC]: 닫기"
        stdscr.addstr(1, max(0, (max_x - len(key_hints)) // 2), key_hints[:max_x - 1], curses.A_DIM)
        
        # ---------------------------------------------------------
        # Tabs Bar
        # ---------------------------------------------------------
        tab_y = 3
        curr_x = 2
        for i, p in enumerate(projects):
            p_badge = "★ " if p == active_proj else ""
            tab_label = f" {i+1}: {p_badge}{p} "
            if curr_x + len(tab_label) >= max_x - 14:
                break
            if i == tab_idx:
                stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
                stdscr.addstr(tab_y, curr_x, tab_label)
                stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)
            else:
                stdscr.addstr(tab_y, curr_x, tab_label, curses.A_DIM)
            curr_x += len(tab_label) + 2

        new_btn = " [+ n:신규] "
        if curr_x + len(new_btn) < max_x - 1:
            stdscr.addstr(tab_y, curr_x, new_btn, curses.color_pair(4) | curses.A_BOLD)

        # ---------------------------------------------------------
        # Project Metadata Bar
        # ---------------------------------------------------------
        meta_y = 5
        status_tag = " [CURRENT ACTIVE] " if is_active else " [SAVED STANDBY] "
        status_color = curses.color_pair(4) if is_active else curses.color_pair(5)
        
        stdscr.addstr(meta_y, 2, f"Project: ", curses.A_BOLD)
        stdscr.addstr(meta_y, 11, current_view_proj.upper(), curses.A_BOLD | curses.color_pair(1))
        stdscr.addstr(meta_y, 11 + len(current_view_proj) + 2, status_tag, status_color | curses.A_BOLD)
        
        path_str = f"Target Path: {proj_info['target_path']}"
        if len(path_str) > max_x - 4:
            path_str = path_str[:max_x - 7] + "..."
        stdscr.addstr(meta_y + 1, 2, path_str, curses.A_DIM)
        
        stack_str = f"Stack: {proj_info['stack']}"
        if len(stack_str) > max_x - 4:
            stack_str = stack_str[:max_x - 7] + "..."
        stdscr.addstr(meta_y + 2, 2, stack_str, curses.A_DIM)

        # ---------------------------------------------------------
        # Split Panels (50% Left: 8 Agents / 50% Right: Recent Tasks)
        # ---------------------------------------------------------
        content_y = 9
        content_h = max_y - content_y - 2
        split_x = max_x // 2  # 전체 팝업 너비의 50%로 정확히 2분할
        
        # 중앙 세로 구분선
        for vy in range(content_y, max_y - 1):
            stdscr.addstr(vy, split_x - 1, "│", curses.A_DIM)
            
        left_w = split_x - 3
        task_x = split_x + 1
        task_w = max_x - task_x - 2
        
        # 좌측: 에이전트 8인 패널 박스 (50% 너비)
        stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(content_y, 2, "🤖 AGENT SQUAD SESSIONS & TOKENS")
        stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
        
        row_y = content_y + 1
        for group in ["Dev1 (기획)", "Dev2 (설계)", "Dev3 (개발)", "Dev4 (검증)"]:
            stdscr.addstr(row_y, 2, f"--- {group} ---", curses.A_DIM)
            row_y += 1
            
            for role_name, cfg in ROLE_CONFIGS.items():
                if cfg["group"] != group:
                    continue
                    
                sess_info = saved_sessions.get(role_name, {})
                session_id = sess_info.get("session_id", "")
                
                # 실시간 상태 또는 세션 저장 상태
                if is_active:
                    st = herdr_statuses.get(role_name, "idle")
                    st_icon = "🟢" if st == "idle" else ("🟡" if st == "working" else "⚪")
                else:
                    st = "saved" if session_id else "new"
                    st_icon = "💾" if session_id else "⚪"
                    
                # 메트릭스 추출
                metrics = get_token_metrics(role_name, cfg["type"], session_id)
                
                line_str = f"{role_name:<11} {st_icon} {st:<5} │ {metrics}"
                if len(line_str) > left_w:
                    line_str = line_str[:left_w - 3] + "..."
                    
                stdscr.addstr(row_y, 2, line_str)
                row_y += 1
            row_y += 1

        # 우측: 태스크 진행 현황 박스 (50% 너비)
        stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(content_y, task_x, f"📋 TASKS ROADMAP ({len(tasks)} Total)")
        stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
        
        t_row_y = content_y + 1
        max_task_rows = content_h - 2
        
        if not tasks:
            stdscr.addstr(t_row_y + 2, task_x + 2, "등록된 태스크가 없습니다.", curses.A_DIM)
        else:
            for task in tasks[:4]:  # 최근 4개 태스크 카드 렌더링
                if t_row_y >= max_y - 4:
                    break
                    
                st_badge = f"[{task['status']}]"
                st_color = curses.color_pair(7) if task["status"] == "COMPLETED" else curses.color_pair(5)
                
                t_head = f"▶ {task['id']} "
                max_head_len = max(10, task_w - len(st_badge) - 2)
                if len(t_head) > max_head_len:
                    t_head = t_head[:max_head_len - 3] + "... "
                stdscr.addstr(t_row_y, task_x, t_head, curses.A_BOLD)
                if task_x + len(t_head) + len(st_badge) < max_x - 1:
                    stdscr.addstr(t_row_y, task_x + len(t_head), st_badge, st_color | curses.A_BOLD)
                t_row_y += 1
                
                t_title = f"  제목: {task['title']}"
                if len(t_title) > task_w:
                    t_title = t_title[:task_w - 3] + "..."
                stdscr.addstr(t_row_y, task_x, t_title, curses.A_DIM)
                t_row_y += 1
                
                t_meta = f"  담당: {task['owner']} │ {task['level']}"
                stdscr.addstr(t_row_y, task_x, t_meta, curses.A_DIM)
                t_row_y += 1
                
                if task["summary"]:
                    t_sum = f"  요약: {task['summary']}"
                    if len(t_sum) > task_w:
                        t_sum = t_sum[:task_w - 3] + "..."
                    stdscr.addstr(t_row_y, task_x, t_sum, curses.A_DIM)
                    t_row_y += 1
                    
                t_row_y += 1  # 카드 간 간격

        # ---------------------------------------------------------
        # Footer Action Bar (Bottom)
        # ---------------------------------------------------------
        footer_y = max_y - 1
        if is_active:
            action_text = f" ✔ 현재 '{current_view_proj}' 프로젝트가 활성화되어 작업 중입니다. "
            stdscr.addstr(footer_y, 2, action_text, curses.color_pair(4) | curses.A_BOLD)
        else:
            action_text = f" ⏎ [Enter]: '{current_view_proj}' 프로젝트로 전체 에이전트 전환 & 세션 복원 "
            stdscr.addstr(footer_y, 2, action_text, curses.color_pair(3) | curses.A_BOLD)
            
        stdscr.refresh()
        
        # ---------------------------------------------------------
        # Key Handling
        # ---------------------------------------------------------
        ch = stdscr.getch()
        if ch in (ord('q'), ord('Q'), 27):  # q or ESC
            break
        elif ch in (curses.KEY_RIGHT, ord('\t'), ord('l')):
            tab_idx = (tab_idx + 1) % len(projects)
        elif ch in (curses.KEY_LEFT, curses.KEY_BTAB, ord('h')):
            tab_idx = (tab_idx - 1 + len(projects)) % len(projects)
        elif ord('1') <= ch <= ord('9'):
            target_idx = ch - ord('1')
            if target_idx < len(projects):
                tab_idx = target_idx
        elif ch in (ord('n'), ord('N')):
            new_proj_path = prompt_new_project_modal(stdscr, projects)
            if new_proj_path:
                switch_target_on_exit = new_proj_path
                break
        elif ch in (curses.KEY_ENTER, 10, 13):
            # 선택된 프로젝트로 스위칭
            if not is_active:
                switch_target_on_exit = current_view_proj
                break
                
    return switch_target_on_exit

def print_terminal_summary():
    """TUI 없이 터미널에 요약 현황을 출력 (CLI 모드)"""
    projects = get_project_list()
    active_proj = get_active_project()
    
    print("\n" + "="*75)
    print(" ⚡ HERDR MULTI-PROJECT & AGENT SQUAD DASHBOARD SUMMARY")
    print("="*75)
    print(f"📌 Current Active Project: [{active_proj.upper()}]\n")
    
    herdr_statuses = get_herdr_agent_statuses()
    
    for p in projects:
        info = get_project_info(p)
        tasks = get_project_tasks(p)
        is_cur = (p == active_proj)
        cur_badge = "★ [CURRENT ACTIVE]" if is_cur else "[STANDBY]"
        
        print(f"📁 Project: {p.upper()} {cur_badge}")
        print(f"   - Target Path: {info['target_path']}")
        print(f"   - Total Tasks: {len(tasks)} tasks registered")
        
        sess_file = PROJECTS_DIR / p / "sessions.json"
        saved_sessions = {}
        if sess_file.exists():
            try:
                saved_sessions = json.loads(sess_file.read_text(encoding="utf-8"))
            except Exception:
                pass
                
        print("   - Agent Squad & Token Status:")
        for role_name, cfg in ROLE_CONFIGS.items():
            s_id = saved_sessions.get(role_name, {}).get("session_id", "")
            if is_cur:
                st = herdr_statuses.get(role_name, "idle")
                st_icon = "🟢" if st == "idle" else ("🟡" if st == "working" else "⚪")
            else:
                st = "saved" if s_id else "new"
                st_icon = "💾" if s_id else "⚪"
            metric = get_token_metrics(role_name, cfg["type"], s_id)
            print(f"     • {role_name:<11} {st_icon} {st:<5} │ {metric}")
            
        if tasks:
            print(f"   - Recent Task: ▶ {tasks[0]['id']} [{tasks[0]['status']}] - {tasks[0]['title']}")
        print("-" * 75)
    print()

def main():
    if "--summary" in sys.argv or "-s" in sys.argv or "--print" in sys.argv or "-p" in sys.argv:
        print_terminal_summary()
        return

    target_to_switch = curses.wrapper(run_tui)
    if target_to_switch:
        print("\n" + "="*60)
        print(f"🚀 Switching Project to: [{target_to_switch}]...")
        print("="*60 + "\n")
        subprocess.run([str(SWITCH_SCRIPT), target_to_switch])

if __name__ == "__main__":
    main()
