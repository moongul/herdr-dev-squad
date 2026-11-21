#!/usr/bin/env python3
"""
Herdr Agent Session & Layout Manager
- Dev 세션의 4개 탭 (Dev1, Dev2, Dev3, Dev4) 및 각 2개 패인 레이아웃 자동 구성
- 역할별 에이전트 기동/세션 복원 (Frontend/Backend: Gemini 4 Hydrogen agy)
- 프로젝트 전환 및 스냅샷 관리
"""

import os
import sys
import json
import time
import signal
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # Dev workspace root
PROJECTS_DIR = BASE_DIR / ".team" / "projects"
ACTIVE_FILE = BASE_DIR / ".team" / "active_project"
HERDR_SESSION = "Dev"

# 4개 탭 및 패인 명세 (각 탭당 2개 역할)
TAB_SPECS = [
    {"tab_label": "Dev1", "roles": ["controller", "planner"]},
    {"tab_label": "Dev2", "roles": ["architector", "designer"]},
    {"tab_label": "Dev3", "roles": ["frontend", "backend"]},
    {"tab_label": "Dev4", "roles": ["reviewer", "qa"]},
]

ROLE_CONFIGS = {
    "controller": {
        "role": "controller",
        "tab_label": "Dev1",
        "agent_type": "agy",
        "base_cmd": "agy --dangerously-skip-permissions --model gemini-3.8-flash",
    },
    "planner": {
        "role": "planner",
        "tab_label": "Dev1",
        "agent_type": "agy",
        "base_cmd": "agy --dangerously-skip-permissions --model gemini-4-neon-medium",
    },
    "architector": {
        "role": "architector",
        "tab_label": "Dev2",
        "agent_type": "pi",
        "base_cmd": "pi --model muse-spark-1.3-contributor",
    },
    "designer": {
        "role": "designer",
        "tab_label": "Dev2",
        "agent_type": "agy",
        "base_cmd": "agy --dangerously-skip-permissions --model gemini-4-argon",
    },
    "frontend": {
        "role": "frontend",
        "tab_label": "Dev3",
        "agent_type": "agy",
        "base_cmd": "agy --dangerously-skip-permissions --model gemini-4-hydrogen",
    },
    "backend": {
        "role": "backend",
        "tab_label": "Dev3",
        "agent_type": "agy",
        "base_cmd": "agy --dangerously-skip-permissions --model gemini-4-hydrogen",
    },
    "reviewer": {
        "role": "reviewer",
        "tab_label": "Dev4",
        "agent_type": "pi",
        "base_cmd": "pi --model muse-spark-1.3-contributor",
    },
    "qa": {
        "role": "qa",
        "tab_label": "Dev4",
        "agent_type": "pi",
        "base_cmd": "pi --model muse-spark-1.3-contributor",
    },
}

ALL_ROLES = list(ROLE_CONFIGS.keys())

AGENTS_CONFIG_FILE = BASE_DIR / ".team" / "agents.json"
if AGENTS_CONFIG_FILE.exists():
    try:
        _custom = json.loads(AGENTS_CONFIG_FILE.read_text(encoding="utf-8"))
        for _role, _ov in (_custom.get("roles") or {}).items():
            if _role in ROLE_CONFIGS and isinstance(_ov, dict):
                for _k in ("tab_label", "agent_type", "base_cmd", "model"):
                    if _k in _ov and _ov[_k]:
                        ROLE_CONFIGS[_role][_k] = _ov[_k]
    except Exception:
        pass

def run_herdr(args: list[str]) -> dict | None:
    cmd = ["herdr", "--session", HERDR_SESSION] + args
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(res.stdout)
    except Exception:
        return None

def is_server_running() -> bool:
    try:
        res = subprocess.run(
            ["herdr", "--session", HERDR_SESSION, "status", "server"],
            capture_output=True, text=True, timeout=2
        )
        return "status: running" in res.stdout
    except Exception:
        return False

def ensure_server():
    """Herdr Dev 세션 서버가 실행 중인지 확인하고 없으면 기동"""
    if is_server_running():
        return
    print(f"[*] Starting herdr headless server for session [{HERDR_SESSION}]...")
    subprocess.Popen(
        ["herdr", "--session", HERDR_SESSION, "server"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setpgrp
    )
    for _ in range(25):
        time.sleep(0.2)
        if is_server_running():
            print(f"[*] Herdr session [{HERDR_SESSION}] server is ready.")
            return
    print(f"[!] Warning: Herdr server startup check timed out.")

def get_active_project() -> str:
    if ACTIVE_FILE.exists():
        try:
            val = ACTIVE_FILE.read_text().strip()
            if val:
                return val
        except Exception:
            pass
    return "default"

def get_opencode_latest_session() -> str | None:
    """opencode session list를 직접 호출하여 가장 최신 세션 ID 추출"""
    try:
        res = subprocess.run(
            ["opencode", "session", "list"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=3
        )
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("ses_"):
                return line.split()[0]
    except Exception:
        pass
    return None

def get_current_panes_by_role() -> dict[str, str]:
    """현재 세션에서 label이 role_name인 pane들을 찾아 {role: pane_id} 매핑 반환"""
    role_to_pane = {}
    data = run_herdr(["pane", "list"])
    if data and "result" in data and "panes" in data["result"]:
        for p in data["result"]["panes"]:
            label = p.get("label")
            pane_id = p.get("pane_id")
            if label in ROLE_CONFIGS and pane_id:
                role_to_pane[label] = pane_id
    return role_to_pane

def get_tabs_info() -> list[dict]:
    data = run_herdr(["tab", "list"])
    if data and "result" in data and "tabs" in data["result"]:
        return data["result"]["tabs"]
    return []

def snapshot_sessions(project_id: str | None = None):
    """현재 실행 중인 8개 에이전트의 세션 ID를 프로젝트 sessions.json에 저장"""
    if not project_id:
        project_id = get_active_project()
    proj_dir = PROJECTS_DIR / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    sessions_file = proj_dir / "sessions.json"

    data = run_herdr(["agent", "list"])
    if not data or "result" not in data or "agents" not in data["result"]:
        return

    agents = data["result"]["agents"]
    saved_sessions = {}
    if sessions_file.exists():
        try:
            with open(sessions_file, "r", encoding="utf-8") as f:
                saved_sessions = json.load(f)
        except Exception:
            saved_sessions = {}

    role_to_pane = get_current_panes_by_role()
    pane_to_role = {pid: r for r, pid in role_to_pane.items()}

    for agent in agents:
        pane_id = agent.get("pane_id")
        role_name = agent.get("name") or pane_to_role.get(pane_id)
        if role_name in ROLE_CONFIGS and pane_id:
            agent_sess = agent.get("agent_session") or {}
            session_val = agent_sess.get("value")
            if ROLE_CONFIGS[role_name]["agent_type"] == "opencode" and not session_val:
                session_val = get_opencode_latest_session()

            if session_val:
                saved_sessions[role_name] = {
                    "pane_id": pane_id,
                    "agent_type": ROLE_CONFIGS[role_name]["agent_type"],
                    "session_id": session_val,
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")
                }

    with open(sessions_file, "w", encoding="utf-8") as f:
        json.dump(saved_sessions, f, indent=2, ensure_ascii=False)
    print(f"[*] Snapshot saved for project [{project_id}]: {len(saved_sessions)} agent sessions in {sessions_file.name}")

def stop_target_agents(exclude_roles: set[str] | None = None):
    """8개 대상 패인의 포그라운드 에이전트 프로세스 종료 (exclude_roles 제외, 완전 종료까지 대기)"""
    exclude = exclude_roles or set()
    role_to_pane = get_current_panes_by_role()
    target_panes = [(r, pid) for r, pid in role_to_pane.items() if r not in exclude]
    print("[*] Stopping target agent processes...")
    for role_name, pane_id in role_to_pane.items():
        if role_name in exclude:
            print(f"  - [{role_name.upper():<11}] {pane_id} ➜ Keeping process (Excluded)")
            continue
        try:
            pinfo = run_herdr(["pane", "process-info", "--pane", pane_id])
            if not pinfo or "result" not in pinfo:
                continue
            res_info = pinfo["result"].get("process_info", {})
            shell_pid = res_info.get("shell_pid")
            fg_procs = res_info.get("foreground_processes", [])
            for proc in fg_procs:
                pid = proc.get("pid")
                if pid and pid != shell_pid:
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
        except Exception:
            pass

    # 포그라운드 프로세스(pi/agy 등)가 실제로 셸로 복귀할 때까지 폴링 대기
    deadline = time.monotonic() + 6.0
    killed_force = False
    while time.monotonic() < deadline:
        remaining = []
        for role_name, pane_id in target_panes:
            try:
                pinfo = run_herdr(["pane", "process-info", "--pane", pane_id])
                if not pinfo or "result" not in pinfo:
                    continue
                res_info = pinfo["result"].get("process_info", {})
                shell_pid = res_info.get("shell_pid")
                fg_procs = [p for p in res_info.get("foreground_processes", []) if p.get("pid") and p.get("pid") != shell_pid]
                if fg_procs:
                    remaining.append((role_name, pane_id, fg_procs))
            except Exception:
                pass
        if not remaining:
            break
        if not killed_force and (deadline - time.monotonic()) < 2.0:
            killed_force = True
            for _, _, fg_procs in remaining:
                for proc in fg_procs:
                    try:
                        os.kill(proc["pid"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        time.sleep(0.3)
    time.sleep(0.3)

def setup_tabs_and_panes() -> dict[str, str]:
    """
    4개 탭(Dev1, Dev2, Dev3, Dev4)을 구성하고,
    각 탭에 정확히 2개의 패인(좌우 split)을 생성하여 역할 라벨을 부여합니다.
    (Work 탭 및 기타 사용자 탭은 보존)
    """
    ensure_server()
    role_to_pane = get_current_panes_by_role()

    # 이미 8개 역할의 패인이 모두 올바르게 매핑되어 있는지 확인
    if len(role_to_pane) == 8:
        # 탭 라벨들도 맞는지 확인
        tabs = {t.get("label"): t for t in get_tabs_info()}
        if all(spec["tab_label"] in tabs for spec in TAB_SPECS):
            print("[*] 4-Tab layout (Dev1, Dev2, Dev3, Dev4) with 8 role panes already present.")
            return role_to_pane

    print("[*] Rebuilding 4-Tab layout (Dev1..Dev4 with 2 panes each)...")
    
    # 1. 기존 에이전트 프로세스 안전 종료
    stop_target_agents()

    # 2. 기존 구형 Dev 탭들 정리 (Work 탭 등은 보존)
    current_tabs = get_tabs_info()
    for t in current_tabs:
        label = t.get("label", "")
        # Dev로 시작하는 기존 탭 닫기
        if label.startswith("Dev"):
            try:
                run_herdr(["tab", "close", t["tab_id"]])
            except Exception:
                pass

    role_to_pane = {}

    # 3. 4개 탭 순차 생성 및 2패인 분할
    for spec in TAB_SPECS:
        tab_label = spec["tab_label"]
        r1, r2 = spec["roles"]

        # 새 탭 생성
        t_res = run_herdr(["tab", "create", "--label", tab_label, "--cwd", str(BASE_DIR)])
        if not t_res or "result" not in t_res:
            print(f"[!] Failed to create tab {tab_label}")
            continue

        p1_info = t_res["result"].get("root_pane", {})
        p1_id = p1_info.get("pane_id")

        # 패인 1 이름 지정
        run_herdr(["pane", "rename", p1_id, r1])
        role_to_pane[r1] = p1_id

        # 패인 2 우측 분할 생성
        split_res = run_herdr(["pane", "split", p1_id, "--direction", "right", "--cwd", str(BASE_DIR), "--no-focus"])
        if split_res and "result" in split_res and "pane" in split_res["result"]:
            p2_id = split_res["result"]["pane"].get("pane_id")
            run_herdr(["pane", "rename", p2_id, r2])
            role_to_pane[r2] = p2_id

        print(f"  - Tab [{tab_label}]: {r1} ({p1_id}) | {r2} ({p2_id})")

    return role_to_pane

def is_valid_session(agent_type: str, session_id: str | None) -> bool:
    """실제 디스크에 저장된 유효한 세션 파일이 존재하는지 검증"""
    if not session_id or not session_id.strip():
        return False
    home = Path.home()
    try:
        if agent_type == "claude":
            # ~/.claude/projects/*/<session_id>.jsonl 확인
            return len(list(home.glob(f".claude/projects/*/{session_id}.jsonl"))) > 0
        elif agent_type == "qoder":
            # ~/.qoder/projects/*/<session_id>.jsonl 확인
            return len(list(home.glob(f".qoder/projects/*/{session_id}.jsonl"))) > 0
        elif agent_type == "agy":
            # ~/.gemini/antigravity-cli/brain/<session_id> 디렉토리 확인
            sess_dir = home / ".gemini" / "antigravity-cli" / "brain" / session_id
            return sess_dir.exists()
        elif agent_type == "pi":
            # 파일 경로이거나 ID 문자열인 경우 모두 검증
            if session_id.startswith("/") and Path(session_id).exists():
                return True
            return len(list(home.glob(f".pi/agent/sessions/*/*{session_id}*.jsonl"))) > 0
    except Exception:
        pass
    return True

def start_target_agents(target_project_id: str | None = None, exclude_roles: set[str] | None = None):
    """타깃 프로젝트의 sessions.json을 참조하여 8개 에이전트 기동/복원"""
    if not target_project_id:
        target_project_id = get_active_project()
    exclude = exclude_roles or set()
    proj_dir = PROJECTS_DIR / target_project_id
    sessions_file = proj_dir / "sessions.json"

    saved_sessions = {}
    if sessions_file.exists():
        try:
            with open(sessions_file, "r", encoding="utf-8") as f:
                saved_sessions = json.load(f)
        except Exception:
            saved_sessions = {}

    role_to_pane = get_current_panes_by_role()
    if len(role_to_pane) < 8:
        role_to_pane = setup_tabs_and_panes()

    print(f"[*] Starting 8 agents for project [{target_project_id}]...")

    for role_name, cfg in ROLE_CONFIGS.items():
        pane_id = role_to_pane.get(role_name)
        if not pane_id:
            print(f"[!] Warning: Pane not found for role {role_name}")
            continue

        if role_name in exclude:
            print(f"  - [{role_name.upper():<11}] {pane_id} ➜ Kept Active (Session preserved)")
            continue

        agent_type = cfg["agent_type"]
        base_cmd = cfg["base_cmd"]
        session_info = saved_sessions.get(role_name, {})
        session_id = session_info.get("session_id")

        if session_id and is_valid_session(agent_type, session_id):
            if agent_type == "agy":
                launch_cmd = f"{base_cmd} --conversation {session_id}"
            elif agent_type == "qoder":
                launch_cmd = f"{base_cmd} -r {session_id}"
            elif agent_type == "claude":
                launch_cmd = f"{base_cmd} -r {session_id}"
            elif agent_type == "pi":
                launch_cmd = f"{base_cmd} --session {session_id}"
            elif agent_type == "opencode":
                launch_cmd = f"{base_cmd} -s {session_id}"
            else:
                launch_cmd = base_cmd
            action_desc = f"Resuming (Session: {session_id[:8]}...)"
        else:
            launch_cmd = base_cmd
            action_desc = "New Fresh Session"

        if role_name == "planner":
            model_desc = "Gemini 4 Neon (agy)"
        elif role_name in ("frontend", "backend"):
            model_desc = "Gemini 4 Hydrogen (agy)"
        elif cfg["agent_type"] == "pi":
            model_desc = "Muse Spark 1.3 (pi)"
        else:
            model_desc = cfg["agent_type"]
        print(f"  - [{role_name.upper():<11}] {pane_id} ({cfg['tab_label']}) ➜ {action_desc} [{model_desc}]")

        run_herdr(["pane", "run", pane_id, launch_cmd])

    # 프로세스 안정화 후 agent label 지정
    time.sleep(1.2)
    for role_name, pane_id in role_to_pane.items():
        run_herdr(["agent", "rename", pane_id, role_name])

    print(f"[*] All agents successfully synchronized for [{target_project_id}].")

def get_status_overview() -> dict:
    """세션, 탭, 에이전트 종합 현황 반환"""
    server_up = is_server_running()
    active_proj = get_active_project()
    role_to_pane = get_current_panes_by_role()
    tabs = get_tabs_info()

    agents_data = run_herdr(["agent", "list"])
    live_agents = {}
    if agents_data and "result" in agents_data and "agents" in agents_data["result"]:
        for ag in agents_data["result"]["agents"]:
            p_id = ag.get("pane_id")
            live_agents[p_id] = ag

    return {
        "server_running": server_up,
        "active_project": active_proj,
        "role_to_pane": role_to_pane,
        "tabs": tabs,
        "live_agents": live_agents,
    }

def main():
    if len(sys.argv) < 2:
        print("Usage: session_manager.py [up | start | stop | status | snapshot <proj> | switch <from> <to>]")
        sys.exit(1)

    cmd = sys.argv[1]
    keep_controller = "--keep-controller" in sys.argv
    exclude_roles = {"controller"} if keep_controller else set()

    if cmd == "up":
        ensure_server()
        setup_tabs_and_panes()
        start_target_agents()
    elif cmd == "snapshot":
        proj = sys.argv[2] if len(sys.argv) >= 3 else None
        snapshot_sessions(proj)
    elif cmd == "stop":
        stop_target_agents(exclude_roles=exclude_roles)
    elif cmd == "start":
        proj = sys.argv[2] if len(sys.argv) >= 3 else None
        start_target_agents(proj, exclude_roles=exclude_roles)
    elif cmd == "switch" and len(sys.argv) >= 4:
        from_proj, to_proj = sys.argv[2], sys.argv[3]
        snapshot_sessions(from_proj)
        stop_target_agents(exclude_roles=exclude_roles)
        start_target_agents(to_proj, exclude_roles=exclude_roles)
    elif cmd == "status":
        overview = get_status_overview()
        print(f"Herdr Server: {'RUNNING' if overview['server_running'] else 'STOPPED'}")
        print(f"Active Project: {overview['active_project']}")
        print("Roles and Panes:")
        for r, pid in overview['role_to_pane'].items():
            ag = overview['live_agents'].get(pid, {})
            st = ag.get("agent_status", "offline")
            print(f"  - {r:<11}: {pid} [{st}]")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

if __name__ == "__main__":
    main()
