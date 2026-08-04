#!/usr/bin/env bash
set -euo pipefail

readonly GUI_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly GUI_DISPLAY="${GUI_DISPLAY:-:99}"
readonly GUI_VNC_PORT="${GUI_VNC_PORT:-5900}"
readonly GUI_NOVNC_PORT="${GUI_NOVNC_PORT:-6080}"
readonly GUI_LOG_PREFIX="/tmp/secret-shop-gui-preview"
readonly GUI_XVFB_LOCK="/tmp/.X${GUI_DISPLAY#:}-lock"

GUI_XVFB_PID=""
GUI_XVFB_SERVER_PID=""
GUI_WINDOW_MANAGER_PID=""
GUI_VNC_PID=""
GUI_NOVNC_PID=""
GUI_APP_PID=""

cleanup_gui_preview() {
    set +e
    for gui_pid in \
        "$GUI_APP_PID" \
        "$GUI_NOVNC_PID" \
        "$GUI_VNC_PID" \
        "$GUI_WINDOW_MANAGER_PID" \
        "$GUI_XVFB_PID"
    do
        if [[ -n "$gui_pid" ]] && kill -0 "$gui_pid" 2>/dev/null; then
            kill "$gui_pid" 2>/dev/null
        fi
    done
    if [[ -n "$GUI_XVFB_SERVER_PID" ]]; then
        sudo kill "$GUI_XVFB_SERVER_PID" 2>/dev/null
    fi
    wait 2>/dev/null
}

trap cleanup_gui_preview EXIT INT TERM

for gui_command in sudo Xvfb xdpyinfo fluxbox x11vnc websockify python; do
    if ! command -v "$gui_command" >/dev/null 2>&1; then
        echo "필수 명령을 찾을 수 없습니다: $gui_command" >&2
        exit 1
    fi
done

cd "$GUI_PROJECT_ROOT"

if [[ -e "$GUI_XVFB_LOCK" ]]; then
    echo "가상 디스플레이 $GUI_DISPLAY가 이미 사용 중입니다." >&2
    exit 1
fi

sudo Xvfb "$GUI_DISPLAY" -screen 0 1280x1024x24 -nolisten tcp -ac \
    >"${GUI_LOG_PREFIX}-xvfb.log" 2>&1 &
GUI_XVFB_PID=$!

for _gui_attempt in {1..50}; do
    if [[ -f "$GUI_XVFB_LOCK" ]]; then
        GUI_XVFB_SERVER_PID="$(tr -d '[:space:]' < "$GUI_XVFB_LOCK")"
    fi
    if env DISPLAY="$GUI_DISPLAY" xdpyinfo >/dev/null 2>&1; then
        break
    fi
    sleep 0.1
done
if ! env DISPLAY="$GUI_DISPLAY" xdpyinfo >/dev/null 2>&1; then
    echo "가상 디스플레이를 시작하지 못했습니다: $GUI_DISPLAY" >&2
    exit 1
fi

env DISPLAY="$GUI_DISPLAY" fluxbox \
    >"${GUI_LOG_PREFIX}-fluxbox.log" 2>&1 &
GUI_WINDOW_MANAGER_PID=$!

env DISPLAY="$GUI_DISPLAY" x11vnc \
    -display "$GUI_DISPLAY" \
    -forever \
    -shared \
    -nopw \
    -localhost \
    -rfbport "$GUI_VNC_PORT" \
    >"${GUI_LOG_PREFIX}-x11vnc.log" 2>&1 &
GUI_VNC_PID=$!

websockify \
    --web=/usr/share/novnc \
    "localhost:$GUI_NOVNC_PORT" \
    "localhost:$GUI_VNC_PORT" \
    >"${GUI_LOG_PREFIX}-novnc.log" 2>&1 &
GUI_NOVNC_PID=$!

sleep 1
if ! kill -0 "$GUI_VNC_PID" 2>/dev/null || ! kill -0 "$GUI_NOVNC_PID" 2>/dev/null; then
    echo "브라우저 GUI 서버를 시작하지 못했습니다. ${GUI_LOG_PREFIX}-*.log를 확인하세요." >&2
    exit 1
fi

env DISPLAY="$GUI_DISPLAY" python main.py &
GUI_APP_PID=$!

echo
echo "비밀상점 GUI 미리보기를 시작했습니다."
echo "포트 ${GUI_NOVNC_PORT}을 브라우저에서 연 뒤 아래 경로로 접속하세요."
echo "/vnc.html?autoconnect=true&resize=scale"
echo "종료하려면 이 터미널에서 Ctrl+C를 누르세요."
echo

wait "$GUI_APP_PID"
