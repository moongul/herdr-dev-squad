#!/usr/bin/env bash
# Switch or Create Active Project for Agent Squad with Session Snapshot & Resume
set -e

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"
DEV_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEAM_DIR="${DEV_ROOT}/.team"
PROJECTS_DIR="${TEAM_DIR}/projects"
ACTIVE_FILE="${TEAM_DIR}/active_project"
SESSION_MGR="${SCRIPT_DIR}/session_manager.py"

# 1. 인자가 없는 경우: 현재 상태 및 목록 출력
if [ -z "$1" ]; then
    CURRENT_ACTIVE="None"
    if [ -f "$ACTIVE_FILE" ]; then
        CURRENT_ACTIVE="$(cat "$ACTIVE_FILE" | tr -d '[:space:]')"
    fi
    
    echo "=================================================="
    echo "📌 Active Project: ${CURRENT_ACTIVE}"
    echo "=================================================="
    echo "Available Projects:"
    for p in "${PROJECTS_DIR}"/*; do
        if [ -d "$p" ]; then
            pname="$(basename "$p")"
            if [ "$pname" != "template" ]; then
                sess_info="No saved sessions"
                if [ -f "$p/sessions.json" ]; then
                    sess_cnt=$(grep -c '"session_id"' "$p/sessions.json" 2>/dev/null || echo 0)
                    sess_info="${sess_cnt} active sessions saved"
                fi
                if [ "$pname" = "$CURRENT_ACTIVE" ]; then
                    echo "  * ${pname} (CURRENT) [${sess_info}]"
                else
                    echo "    ${pname} [${sess_info}]"
                fi
            fi
        fi
    done
    echo "--------------------------------------------------"
    echo "Usage:"
    echo "  ./switch-project.sh <project_name_or_path> [--keep-controller]"
    echo "Examples:"
    echo "  ./switch-project.sh claude"
    echo "  ./switch-project.sh ~/Work/Blog"
    echo "  ./switch-project.sh ~/Work/Dashboard --keep-controller"
    echo "=================================================="
    exit 0
fi

KEEP_CONTROLLER_FLAG=""
ARGS=()
for arg in "$@"; do
    if [ "$arg" = "--keep-controller" ]; then
        KEEP_CONTROLLER_FLAG="--keep-controller"
    else
        ARGS+=("$arg")
    fi
done

if [ ${#ARGS[@]} -eq 0 ]; then
    echo "[!] Error: Project name or path is required."
    exit 1
fi

INPUT_TARGET="${ARGS[0]}"

# 물결표(~) 홈 디렉토리 확장
if [[ "$INPUT_TARGET" == "~"* ]]; then
    INPUT_TARGET="${HOME}${INPUT_TARGET:1}"
fi

# 디렉토리 경로인지 또는 단순 이름인지 판별
if [[ "$INPUT_TARGET" == *"/"* ]] || [ -d "$INPUT_TARGET" ]; then
    INPUT_TARGET="${INPUT_TARGET%/}"
    if [ ! -d "$INPUT_TARGET" ]; then
        echo "[*] Creating target project directory: '${INPUT_TARGET}'..."
        mkdir -p "$INPUT_TARGET"
    fi
    RESOLVED_PATH="$(cd "$INPUT_TARGET" 2>/dev/null && pwd || echo "$INPUT_TARGET")"
    PROJECT_NAME="$(basename "$RESOLVED_PATH")"
    PROJECT_ID="$(echo "$PROJECT_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')"
else
    PROJECT_ID="$(echo "$INPUT_TARGET" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')"
    PROJECT_NAME="$INPUT_TARGET"
    WORK_ROOT="${DEV_WORK_DIR:-$(dirname "$DEV_ROOT")}"
    if [ -d "${WORK_ROOT}/${INPUT_TARGET}" ]; then
        RESOLVED_PATH="${WORK_ROOT}/${INPUT_TARGET}"
    else
        RESOLVED_PATH="${WORK_ROOT}/${PROJECT_NAME}"
    fi
fi

PREV_PROJECT="default"
if [ -f "$ACTIVE_FILE" ]; then
    PREV_PROJECT="$(cat "$ACTIVE_FILE" | tr -d '[:space:]')"
fi

TARGET_PROJECT_DIR="${PROJECTS_DIR}/${PROJECT_ID}"

# 신규 프로젝트 생성 여부 확인
IS_NEW=0
if [ ! -d "$TARGET_PROJECT_DIR" ]; then
    IS_NEW=1
    echo "[*] Initializing new project space for: '${PROJECT_ID}'..."
    mkdir -p "$TARGET_PROJECT_DIR"
    
    if [ -d "${PROJECTS_DIR}/template" ]; then
        cp -r "${PROJECTS_DIR}/template"/* "$TARGET_PROJECT_DIR"/
    else
        mkdir -p "${TARGET_PROJECT_DIR}/tasks"
        touch "${TARGET_PROJECT_DIR}/PROJECT.md"
        touch "${TARGET_PROJECT_DIR}/TASKS.md"
    fi
    
    if [ -f "${TARGET_PROJECT_DIR}/PROJECT.md" ]; then
        sed -i "s|{{PROJECT_NAME}}|${PROJECT_NAME}|g" "${TARGET_PROJECT_DIR}/PROJECT.md"
        sed -i "s|{{PROJECT_PATH}}|${RESOLVED_PATH}|g" "${TARGET_PROJECT_DIR}/PROJECT.md"
    fi
    if [ -f "${TARGET_PROJECT_DIR}/TASKS.md" ]; then
        sed -i "s|{{PROJECT_NAME}}|${PROJECT_NAME}|g" "${TARGET_PROJECT_DIR}/TASKS.md"
    fi
fi

# 1. 이전 프로젝트의 에이전트 세션 저장 & 종료 & 타깃 프로젝트 세션 복원
if [ -f "$SESSION_MGR" ]; then
    echo "--------------------------------------------------"
    echo "[*] Managing Herdr Agent Sessions (Snapshot & Resume)..."
    python3 "$SESSION_MGR" switch "$PREV_PROJECT" "$PROJECT_ID" $KEEP_CONTROLLER_FLAG
    echo "--------------------------------------------------"
fi

# 2. active_project 파일 갱신
echo "$PROJECT_ID" > "$ACTIVE_FILE"

# 3. 심볼릭 링크 갱신
cd "$DEV_ROOT"
rm -f PROJECT.md
ln -s ".team/projects/${PROJECT_ID}/PROJECT.md" PROJECT.md

cd "$TEAM_DIR"
rm -f TASKS.md
ln -s "projects/${PROJECT_ID}/TASKS.md" TASKS.md
rm -f tasks
ln -s "projects/${PROJECT_ID}/tasks" tasks

# 4. Herdr Workspace 라벨에만 현재 프로젝트명 표시
if command -v herdr >/dev/null 2>&1; then
    ACTIVE_WS=$(python3 -c "
import subprocess, json
try:
    res = subprocess.run(['herdr', '--session', 'Dev', 'pane', 'list'], capture_output=True, text=True)
    panes = json.loads(res.stdout).get('result', {}).get('panes', [])
    for p in panes:
        if p.get('label') == 'controller' and p.get('workspace_id'):
            print(p['workspace_id'])
            break
except Exception:
    pass
" 2>/dev/null)
    herdr --session Dev workspace rename "${ACTIVE_WS:-w1}" "Dev [${PROJECT_ID}]" >/dev/null 2>&1 || true
fi

echo "=================================================="
if [ "$IS_NEW" -eq 1 ]; then
    echo "🎉 Successfully CREATED and SWITCHED to project: '${PROJECT_ID}'"
else
    echo "✅ Successfully SWITCHED to project: '${PROJECT_ID}'"
fi
echo " - Project ID:     ${PROJECT_ID}"
echo " - Target Code:    ${RESOLVED_PATH}"
echo " - Tasks Dir:      .team/projects/${PROJECT_ID}/tasks"
echo " - Spec File:      .team/projects/${PROJECT_ID}/PROJECT.md"
echo " - Sessions State: .team/projects/${PROJECT_ID}/sessions.json"
echo "=================================================="
