"""
GUI 인터페이스
tkinter를 사용한 사용자 인터페이스
"""
import contextvars
import logging
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# libpng 경고 메시지 숨기기 (cv2 import 전에 설정)
os.environ["OPENCV_LOG_LEVEL"] = "ERROR"

from .adb_controller import ADBController
from .image_matcher import read_image
from .json_macro_engine import JsonMacroEngine
from .remote_script import RemoteScriptUpdater
from .secret_shop_bot import SecretShopBot

logger = logging.getLogger(__name__)
LOG_SESSION = contextvars.ContextVar("log_session", default="App")


@contextmanager
def log_session(session_name: str):
    token = LOG_SESSION.set(session_name)
    try:
        yield
    finally:
        LOG_SESSION.reset(token)


class SessionContextFilter(logging.Filter):
    def filter(self, record):
        record.session_name = LOG_SESSION.get("App")
        return True


class TextHandler(logging.Handler):
    """세션별 로그를 텍스트 위젯에 출력하는 핸들러"""

    def __init__(self, text_widget, session_name):
        super().__init__()
        self.text_widget = text_widget
        self.session_name = session_name

    def emit(self, record):
        record_session = getattr(record, "session_name", "App")
        if record_session not in (self.session_name, "App"):
            return

        msg = self.format(record)

        def append():
            is_at_bottom = self.text_widget.yview()[1] >= 0.99
            self.text_widget.configure(state="normal")
            self.text_widget.insert(tk.END, msg + "\n")
            self.text_widget.configure(state="disabled")
            if is_at_bottom:
                self.text_widget.yview(tk.END)

        self.text_widget.after(0, append)


class SessionView:
    """하나의 앱플레이어/봇 세션을 관리합니다."""

    def __init__(self, app, index: int, parent):
        self.app = app
        self.index = index
        self.name = f"세션 {index}"
        self.session_id = f"session_{index}"
        self.root = parent
        self.runtime_dir = Path("logs") / self.session_id
        self.adb_controller = None
        self.bot = None
        self.bot_thread = None
        self.is_running = False
        self.selected_macro_id = "secret_shop"

        self.frame = ttk.Frame(parent)
        self._create_widgets()

    def _create_widgets(self):
        self.connection_frame = ttk.LabelFrame(self.frame, text="ADB 연결", padding=10)
        self.connection_frame.pack(fill=tk.X, padx=10, pady=5)

        self.ip_label = ttk.Label(self.connection_frame, text="IP 주소:")
        self.ip_label.grid(row=0, column=0, sticky=tk.W, padx=5)
        self.ip_entry = ttk.Entry(self.connection_frame, width=15)
        self.ip_entry.insert(0, "127.0.0.1")
        self.ip_entry.grid(row=0, column=1, padx=5)

        self.port_label = ttk.Label(self.connection_frame, text="포트:")
        self.port_label.grid(row=0, column=2, sticky=tk.W, padx=5)
        self.port_entry = ttk.Entry(self.connection_frame, width=8)
        self.port_entry.insert(0, "5555")
        self.port_entry.grid(row=0, column=3, padx=5)

        self.scan_btn = ttk.Button(self.connection_frame, text="장치 검색", command=self._scan_devices)
        self.scan_btn.grid(row=0, column=4, padx=5)

        self.connect_btn = ttk.Button(self.connection_frame, text="연결", command=self._connect_adb)
        self.connect_btn.grid(row=0, column=5, padx=5)

        self.disconnect_btn = ttk.Button(
            self.connection_frame,
            text="연결 해제",
            command=self._disconnect_adb,
            state=tk.DISABLED,
        )
        self.disconnect_btn.grid(row=0, column=6, padx=5)

        self.connection_status = ttk.Label(self.connection_frame, text="● 연결 안됨", foreground="red")
        self.connection_status.grid(row=0, column=7, padx=10)

        self.device_label = ttk.Label(self.connection_frame, text="장치:")
        self.device_label.grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.device_combo = ttk.Combobox(self.connection_frame, width=30, state="readonly")
        self.device_combo.grid(row=1, column=1, columnspan=4, sticky=tk.W, padx=5, pady=5)
        self.device_combo.bind("<<ComboboxSelected>>", self._on_device_selected)

        self.settings_frame = ttk.LabelFrame(self.frame, text="매크로 설정", padding=10)
        self.settings_frame.pack(fill=tk.X, padx=10, pady=5)

        self.refresh_count_label = ttk.Label(self.settings_frame, text="리프레시 횟수:")
        self.refresh_count_label.grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.refresh_count_entry = ttk.Entry(self.settings_frame, width=10)
        self.refresh_count_entry.insert(0, "100")
        self.refresh_count_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        self.refresh_count_unit_label = ttk.Label(self.settings_frame, text="회")
        self.refresh_count_unit_label.grid(row=0, column=2, sticky=tk.W)

        self.buy_count_label = ttk.Label(self.settings_frame, text="구매 완료 검증 횟수:")
        self.buy_count_label.grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.buy_count_entry = ttk.Entry(self.settings_frame, width=10)
        self.buy_count_entry.insert(0, "3")
        self.buy_count_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        self.buy_count_unit_label = ttk.Label(self.settings_frame, text="회 (비활성화 버튼 확인 반복, 권장: 3회)")
        self.buy_count_unit_label.grid(row=1, column=2, sticky=tk.W)

        self.threshold_header_label = ttk.Label(
            self.settings_frame,
            text="=== 이미지 매칭 정확도 (70-99) ===",
            font=("Arial", 9, "bold"),
        )
        self.threshold_header_label.grid(row=2, column=0, columnspan=3, sticky=tk.W, padx=5, pady=(10, 5))

        self.mystic_medal_threshold_label = ttk.Label(self.settings_frame, text="신비의 메달:")
        self.mystic_medal_threshold_label.grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.mystic_medal_threshold = ttk.Entry(self.settings_frame, width=8)
        self.mystic_medal_threshold.insert(0, "92")
        self.mystic_medal_threshold.grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(self.settings_frame, text="%").grid(row=3, column=2, sticky=tk.W)

        self.covenant_bookmark_threshold_label = ttk.Label(self.settings_frame, text="성약의 책갈피:")
        self.covenant_bookmark_threshold_label.grid(row=4, column=0, sticky=tk.W, padx=5, pady=2)
        self.covenant_bookmark_threshold = ttk.Entry(self.settings_frame, width=8)
        self.covenant_bookmark_threshold.insert(0, "92")
        self.covenant_bookmark_threshold.grid(row=4, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(self.settings_frame, text="%").grid(row=4, column=2, sticky=tk.W)

        self.purchase_button_threshold_label = ttk.Label(self.settings_frame, text="구입 버튼:")
        self.purchase_button_threshold_label.grid(row=5, column=0, sticky=tk.W, padx=5, pady=2)
        self.purchase_button_threshold = ttk.Entry(self.settings_frame, width=8)
        self.purchase_button_threshold.insert(0, "92")
        self.purchase_button_threshold.grid(row=5, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(self.settings_frame, text="%").grid(row=5, column=2, sticky=tk.W)

        self.buy_button_threshold_label = ttk.Label(self.settings_frame, text="구매 버튼:")
        self.buy_button_threshold_label.grid(row=6, column=0, sticky=tk.W, padx=5, pady=2)
        self.buy_button_threshold = ttk.Entry(self.settings_frame, width=8)
        self.buy_button_threshold.insert(0, "92")
        self.buy_button_threshold.grid(row=6, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(self.settings_frame, text="%").grid(row=6, column=2, sticky=tk.W)

        self.refresh_button_threshold_label = ttk.Label(self.settings_frame, text="갱신 버튼:")
        self.refresh_button_threshold_label.grid(row=7, column=0, sticky=tk.W, padx=5, pady=2)
        self.refresh_button_threshold = ttk.Entry(self.settings_frame, width=8)
        self.refresh_button_threshold.insert(0, "92")
        self.refresh_button_threshold.grid(row=7, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(self.settings_frame, text="%").grid(row=7, column=2, sticky=tk.W)

        self.debug_mode_var = tk.BooleanVar(value=False)
        self.debug_checkbox = ttk.Checkbutton(
            self.settings_frame,
            text="디버그 모드 (상세 로그)",
            variable=self.debug_mode_var,
        )
        self.debug_checkbox.grid(row=8, column=0, columnspan=2, sticky=tk.W, padx=5, pady=5)

        control_frame = ttk.Frame(self.frame, padding=10)
        control_frame.pack(fill=tk.X, padx=10, pady=5)

        self.macro_select_label = ttk.Label(control_frame, text="매크로:")
        self.macro_select_label.pack(side=tk.LEFT, padx=(0, 5))

        self.macro_combo = ttk.Combobox(control_frame, width=22, state="readonly")
        self.macro_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.refresh_macro_combo()

        self.start_btn = ttk.Button(control_frame, text="▶ 시작", command=self._start_bot, state=tk.DISABLED)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.pause_btn = ttk.Button(control_frame, text="⏸ 일시정지", command=self._pause_bot, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=5)

        self.resume_btn = ttk.Button(control_frame, text="▶ 재개", command=self._resume_bot, state=tk.DISABLED)
        self.resume_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(control_frame, text="■ 중지", command=self._stop_bot, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.test_btn = ttk.Button(control_frame, text="💡 이미지 테스트", command=self._test_image_matching, state=tk.DISABLED)
        self.test_btn.pack(side=tk.LEFT, padx=5)

        self.pause_label = ttk.Label(control_frame, text="", foreground="orange", font=("Arial", 10, "bold"))
        self.pause_label.pack(side=tk.LEFT, padx=10)

        self.stats_frame = ttk.LabelFrame(self.frame, text="통계", padding=10)
        self.stats_frame.pack(fill=tk.X, padx=10, pady=5)

        stats_grid = ttk.Frame(self.stats_frame)
        stats_grid.pack(fill=tk.X)

        self.total_refresh_title_label = ttk.Label(stats_grid, text="진행 완료:")
        self.total_refresh_title_label.grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.total_refresh_label = ttk.Label(stats_grid, text="0", foreground="blue", font=("Arial", 10, "bold"))
        self.total_refresh_label.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)

        self.mystic_title_label = ttk.Label(stats_grid, text="신비의 메달:")
        self.mystic_title_label.grid(row=0, column=2, sticky=tk.W, padx=5, pady=2)
        self.mystic_label = ttk.Label(stats_grid, text="0", foreground="blue", font=("Arial", 10, "bold"))
        self.mystic_label.grid(row=0, column=3, sticky=tk.W, padx=5, pady=2)

        self.bookmark_title_label = ttk.Label(stats_grid, text="성약의 책갈피:")
        self.bookmark_title_label.grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.bookmark_label = ttk.Label(stats_grid, text="0", foreground="blue", font=("Arial", 10, "bold"))
        self.bookmark_label.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)

        self.elapsed_time_title_label = ttk.Label(stats_grid, text="경과 시간:")
        self.elapsed_time_title_label.grid(row=1, column=2, sticky=tk.W, padx=5, pady=2)
        self.elapsed_time_label = ttk.Label(stats_grid, text="00:00:00", foreground="blue", font=("Arial", 10, "bold"))
        self.elapsed_time_label.grid(row=1, column=3, sticky=tk.W, padx=5, pady=2)

        self.log_frame = ttk.LabelFrame(self.frame, text="로그", padding=10)
        self.log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.log_text = scrolledtext.ScrolledText(self.log_frame, state="disabled", height=20, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def add_log_handler(self):
        text_handler = TextHandler(self.log_text, self.name)
        text_handler.addFilter(SessionContextFilter())
        text_handler.setFormatter(logging.Formatter("%(asctime)s - [%(session_name)s] - %(levelname)s - %(message)s"))
        logging.getLogger().addHandler(text_handler)

    def refresh_macro_combo(self):
        labels = [macro.get("name", macro.get("id", "macro")) for macro in self.app.macro_definitions]
        self.macro_combo["values"] = labels
        selected_index = 0
        for index, macro in enumerate(self.app.macro_definitions):
            if macro.get("id") == self.selected_macro_id:
                selected_index = index
                break
        if labels:
            self.macro_combo.current(selected_index)

    def apply_settings_update(self, config):
        self.apply_remote_gui(config.get("gui", {}))
        self.refresh_macro_combo()
        if self.is_running:
            return

        defaults = config.get("defaults", {})
        thresholds = config.get("thresholds", {})
        if "refresh_count" in defaults:
            self._replace_entry(self.refresh_count_entry, defaults["refresh_count"])
        if "purchase_verification_count" in defaults:
            self._replace_entry(self.buy_count_entry, defaults["purchase_verification_count"])

        threshold_entries = {
            "mystic_medal": self.mystic_medal_threshold,
            "covenant_bookmark": self.covenant_bookmark_threshold,
            "purchase_button": self.purchase_button_threshold,
            "buy_button": self.buy_button_threshold,
            "refresh_button": self.refresh_button_threshold,
        }
        for key, entry in threshold_entries.items():
            if key in thresholds:
                self._replace_entry(entry, thresholds[key])

    def apply_remote_gui(self, gui_config):
        if not isinstance(gui_config, dict):
            return

        sections = gui_config.get("sections", {})
        section_widgets = {
            "connection": self.connection_frame,
            "settings": self.settings_frame,
            "stats": self.stats_frame,
            "log": self.log_frame,
        }
        for key, widget in section_widgets.items():
            if key in sections:
                widget.config(text=sections[key])

        labels = gui_config.get("labels", {})
        label_widgets = {
            "macro": self.macro_select_label,
            "ip": self.ip_label,
            "port": self.port_label,
            "device": self.device_label,
            "refresh_count": self.refresh_count_label,
            "refresh_count_unit": self.refresh_count_unit_label,
            "purchase_verification_count": self.buy_count_label,
            "purchase_verification_count_unit": self.buy_count_unit_label,
            "threshold_header": self.threshold_header_label,
            "mystic_medal": self.mystic_medal_threshold_label,
            "covenant_bookmark": self.covenant_bookmark_threshold_label,
            "purchase_button": self.purchase_button_threshold_label,
            "buy_button": self.buy_button_threshold_label,
            "refresh_button": self.refresh_button_threshold_label,
        }
        for key, widget in label_widgets.items():
            if key in labels:
                widget.config(text=labels[key])
        if "debug_mode" in labels:
            self.debug_checkbox.config(text=labels["debug_mode"])

        buttons = gui_config.get("buttons", {})
        button_widgets = {
            "scan": self.scan_btn,
            "connect": self.connect_btn,
            "disconnect": self.disconnect_btn,
            "start": self.start_btn,
            "pause": self.pause_btn,
            "resume": self.resume_btn,
            "stop": self.stop_btn,
            "image_test": self.test_btn,
        }
        for key, widget in button_widgets.items():
            if key in buttons:
                widget.config(text=buttons[key])

        stats = gui_config.get("stats", {})
        stat_widgets = {
            "total_refreshes": self.total_refresh_title_label,
            "mystic_medal": self.mystic_title_label,
            "covenant_bookmark": self.bookmark_title_label,
            "elapsed_time": self.elapsed_time_title_label,
        }
        for key, widget in stat_widgets.items():
            if key in stats:
                widget.config(text=stats[key])

    def _replace_entry(self, entry, value):
        entry.delete(0, tk.END)
        entry.insert(0, str(value))

    def _scan_devices(self):
        with log_session(self.name):
            try:
                temp_adb = ADBController()
                devices = temp_adb.get_devices()
                if not devices:
                    logger.warning("⚠️ 연결된 장치가 없습니다. 앱플레이어의 ADB 브릿지/ADB 디버깅 옵션이 활성화되어 있는지 확인하세요.")
                    self.device_combo["values"] = []
                    return

                unavailable_devices = [d for d in devices if d.get("status") != "device"]
                if unavailable_devices:
                    logger.warning(
                        "⚠️ ADB 장치가 정상 상태가 아닙니다: %s. 앱플레이어의 ADB 브릿지/ADB 디버깅 옵션을 확인하세요.",
                        unavailable_devices,
                    )

                device_list = [f"{d['id']} ({d['status']})" for d in devices]
                self.device_combo["values"] = device_list
                if device_list:
                    self.device_combo.current(0)
                    self._on_device_selected(None)
                logger.info("🔍 장치 %s개 발견: %s", len(devices), [d["id"] for d in devices])
            except Exception as e:
                logger.error("장치 검색 중 오류: %s", e)

    def _on_device_selected(self, event):
        if self.device_combo.get():
            device_id = self.device_combo.get().split(" (")[0]
            if ":" in device_id:
                ip, port = device_id.split(":", 1)
                self._replace_entry(self.ip_entry, ip)
                self._replace_entry(self.port_entry, port)

    def _connect_adb(self):
        with log_session(self.name):
            ip = self.ip_entry.get().strip()
            port = self.port_entry.get().strip()
            if not ip or not port:
                messagebox.showerror("오류", "IP 주소와 포트를 입력하세요.")
                return
            try:
                port = int(port)
            except ValueError:
                messagebox.showerror("오류", "포트는 숫자여야 합니다.")
                return

            device_id = f"{ip}:{port}"
            if self.app.is_device_in_use(device_id, self):
                self.connection_status.config(text="● 사용 중", foreground="red")
                logger.error("❌ %s 장치는 다른 세션에서 이미 사용 중입니다.", device_id)
                return

            self.adb_controller = ADBController()
            if self.adb_controller.connect(ip, port):
                logger.info("ADB 테스트 통신 확인 중...")
                test_ok, test_message = self.adb_controller.test_connection()
                if test_ok:
                    self.connection_status.config(text="● 연결됨", foreground="green")
                    self.start_btn.config(state=tk.NORMAL)
                    self.test_btn.config(state=tk.NORMAL)
                    self.connect_btn.config(state=tk.DISABLED)
                    self.disconnect_btn.config(state=tk.NORMAL)
                    logger.info("✅ ADB 연결 및 테스트 통신 성공: %s", device_id)
                else:
                    self.connection_status.config(text="● 통신 실패", foreground="red")
                    logger.error("❌ ADB 테스트 통신 실패: %s", test_message)
                    logger.error("앱플레이어의 ADB 브릿지/ADB 디버깅 옵션이 활성화되어 있는지 확인한 뒤 다시 연결하세요.")
                    self.adb_controller.disconnect()
                    self.adb_controller = None
            else:
                self.connection_status.config(text="● 연결 실패", foreground="red")
                logger.error("❌ ADB 연결 실패: %s - 앱플레이어 실행 상태와 ADB 브릿지/ADB 디버깅 옵션을 확인하세요", device_id)
                self.adb_controller = None

    def _start_bot(self):
        with log_session(self.name):
            if self.is_running:
                return
            if not self.adb_controller:
                messagebox.showerror("오류", "ADB가 연결되지 않았습니다.")
                return

            try:
                refresh_count = int(self.refresh_count_entry.get())
                buy_count = int(self.buy_count_entry.get())
                thresholds = {
                    key: int(value) / 100.0
                    for key, value in self.app.remote_settings.get("thresholds", {}).items()
                }
                thresholds.update({
                    "mystic_medal": int(self.mystic_medal_threshold.get()) / 100.0,
                    "covenant_bookmark": int(self.covenant_bookmark_threshold.get()) / 100.0,
                    "purchase_button": int(self.purchase_button_threshold.get()) / 100.0,
                    "buy_button": int(self.buy_button_threshold.get()) / 100.0,
                    "refresh_button": int(self.refresh_button_threshold.get()) / 100.0,
                })
                if refresh_count <= 0 or buy_count <= 0:
                    raise ValueError()
                for key, val in thresholds.items():
                    if not 0.7 <= val <= 0.99:
                        raise ValueError(f"{key} 임계값은 70~99 사이여야 합니다.")
            except ValueError as e:
                messagebox.showerror(
                    "오류",
                    f"설정값이 올바르지 않습니다.\n{str(e)}\n리프레시 횟수와 구매 횟수는 양수여야 하며,\n매칭 정확도는 70~99 사이여야 합니다.",
                )
                return

            selected_macro = self._get_selected_macro()
            runner = selected_macro.get("runner", "secret_shop")
            debug_mode = self.debug_mode_var.get()
            self.runtime_dir.mkdir(parents=True, exist_ok=True)

            if runner == "steps":
                self.bot = JsonMacroEngine(
                    self.adb_controller,
                    macro_definition=selected_macro,
                    runtime_dir=str(self.runtime_dir),
                    thresholds=thresholds,
                    debug_mode=debug_mode,
                    automation_settings=self.app.remote_settings,
                )
            else:
                self.bot = SecretShopBot(
                    self.adb_controller,
                    runtime_dir=str(self.runtime_dir),
                    thresholds=thresholds,
                    debug_mode=debug_mode,
                    automation_settings=self.app.remote_settings,
                )

            self.is_running = True
            self._set_running_ui(True)
            self._update_stats({
                "total_refreshes": 0,
                "completed_runs": 0,
                "successful_refreshes": 0,
                "mystic_medal_bought": 0,
                "covenant_bookmark_bought": 0,
            })
            self.bot_thread = threading.Thread(target=self._run_bot, args=(refresh_count, buy_count), daemon=True)
            self.bot_thread.start()

    def _get_selected_macro(self):
        selected_index = self.macro_combo.current()
        if selected_index < 0 or selected_index >= len(self.app.macro_definitions):
            selected_index = 0
        macro = self.app.macro_definitions[selected_index]
        self.selected_macro_id = macro.get("id", "secret_shop")
        return macro

    def _run_bot(self, refresh_count, buy_count):
        with log_session(self.name):
            try:
                self.root.after(500, self._update_running_state)
                final_stats = self.bot.run(refresh_count, buy_count)
                self.root.after(0, lambda: self._update_stats(final_stats))
                self.log(self._format_stats_summary("✅ 자동화 완료", final_stats))
            except Exception as e:
                logger.error("봇 실행 중 오류: %s", e, exc_info=True)
                if not self.app.is_closing:
                    self.root.after(0, lambda: messagebox.showerror("오류", f"{self.name} 실행 중 오류 발생:\n{str(e)}"))
            finally:
                self.is_running = False
                if not self.app.is_closing:
                    self.root.after(0, lambda: self._set_running_ui(False))

    def _update_running_state(self):
        if self.is_running and self.bot:
            self._update_stats(self.bot.get_stats())
            if self.bot.paused:
                self.pause_label.config(text="⏸️  일시정지 중")
                self.pause_btn.config(state=tk.DISABLED)
                self.resume_btn.config(state=tk.NORMAL)
            else:
                self.pause_label.config(text="")
                self.pause_btn.config(state=tk.NORMAL)
                self.resume_btn.config(state=tk.DISABLED)
            self.root.after(500, self._update_running_state)

    def _pause_bot(self):
        with log_session(self.name):
            if self.bot:
                self.bot.set_user_action("pause")
                self.log("⏸️ 일시정지 요청됨")
                self.pause_label.config(text="⏸️  일시정지 중")
                self.pause_btn.config(state=tk.DISABLED)
                self.resume_btn.config(state=tk.NORMAL)

    def _resume_bot(self):
        with log_session(self.name):
            if self.bot:
                self.bot.set_user_action("resume")
                self.log("▶️ 재개 요청됨")
                self.pause_label.config(text="")
                self.pause_btn.config(state=tk.NORMAL)
                self.resume_btn.config(state=tk.DISABLED)

    def _stop_bot(self):
        with log_session(self.name):
            if not self.is_running:
                return
            if self.bot:
                self.bot.set_user_action("stop")
            self.is_running = False
            if self.bot:
                stats = self.bot.get_stats()
                if stats.get("total_refreshes", 0) > 0:
                    self.log(self._format_stats_summary("⛔ 자동화 중지", stats))
                else:
                    self.log("⛔ 봇이 중지되었습니다.")

    def request_stop_for_close(self):
        with log_session(self.name):
            if self.bot:
                self.bot.set_user_action("stop")
            self.is_running = False

    def cleanup_on_close(self):
        with log_session(self.name):
            if self.adb_controller:
                self.adb_controller.disconnect()
                self.adb_controller = None
                logger.info("앱 종료 - 이 세션의 ADB 장치 연결만 해제했습니다. ADB 서버는 다른 세션 보호를 위해 유지됩니다.")

    def _disconnect_adb(self):
        with log_session(self.name):
            if self.is_running:
                messagebox.showwarning("경고", "봇이 실행 중일 때는 연결을 해제할 수 없습니다.")
                return
            if self.adb_controller:
                self.adb_controller.disconnect()
                self.adb_controller = None
            self.connection_status.config(text="● 연결 안됨", foreground="red")
            self.start_btn.config(state=tk.DISABLED)
            self.test_btn.config(state=tk.DISABLED)
            self.connect_btn.config(state=tk.NORMAL)
            self.disconnect_btn.config(state=tk.DISABLED)
            self.log("✅ ADB 연결이 해제되었습니다.")

    def _set_running_ui(self, running):
        self.start_btn.config(state=tk.DISABLED if running else (tk.NORMAL if self.adb_controller else tk.DISABLED))
        self.test_btn.config(state=tk.DISABLED if running else (tk.NORMAL if self.adb_controller else tk.DISABLED))
        self.pause_btn.config(state=tk.NORMAL if running else tk.DISABLED)
        self.resume_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL if running else tk.DISABLED)
        self.connect_btn.config(state=tk.DISABLED if running or self.adb_controller else tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED if running else (tk.NORMAL if self.adb_controller else tk.DISABLED))
        self.macro_combo.config(state=tk.DISABLED if running else "readonly")
        self.pause_label.config(text="")

        state = tk.DISABLED if running else tk.NORMAL
        for entry in (
            self.refresh_count_entry,
            self.buy_count_entry,
            self.mystic_medal_threshold,
            self.covenant_bookmark_threshold,
            self.purchase_button_threshold,
            self.buy_button_threshold,
            self.refresh_button_threshold,
        ):
            entry.config(state=state)
        self.debug_checkbox.config(state=state)

    def _update_stats(self, stats):
        completed_runs = stats.get("completed_runs", stats.get("total_refreshes", 0))
        self.total_refresh_label.config(text=str(completed_runs))
        self.mystic_label.config(text=str(stats.get("mystic_medal_bought", 0)))
        self.bookmark_label.config(text=str(stats.get("covenant_bookmark_bought", 0)))

        if stats.get("start_time"):
            if stats.get("end_time"):
                elapsed = int(stats["end_time"] - stats["start_time"])
            else:
                elapsed = int(time.time() - stats["start_time"])
            hours = elapsed // 3600
            minutes = (elapsed % 3600) // 60
            seconds = elapsed % 60
            self.elapsed_time_label.config(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        else:
            self.elapsed_time_label.config(text="00:00:00")

    def _format_stats_summary(self, title, stats):
        completed_runs = stats.get("completed_runs", stats.get("total_refreshes", 0))
        successful_refreshes = stats.get("successful_refreshes", max(completed_runs - 1, 0))
        mystic_count = stats.get("mystic_medal_bought", 0)
        bookmark_count = stats.get("covenant_bookmark_bought", 0)
        elapsed = self._format_elapsed_seconds(stats.get("elapsed_time", 0))
        return (
            f"\n{'=' * 42}\n"
            f"{title}\n"
            f"- 진행 완료: {completed_runs}회\n"
            f"- 갱신 성공: {successful_refreshes}회\n"
            f"- 신비의 메달 구매: {mystic_count}개\n"
            f"- 성약의 책갈피 구매: {bookmark_count}개\n"
            f"- 소요 시간: {elapsed}\n"
            f"{'=' * 42}"
        )

    def _format_elapsed_seconds(self, seconds):
        try:
            seconds = int(seconds)
        except (TypeError, ValueError):
            seconds = 0
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        remaining_seconds = seconds % 60
        if hours:
            return f"{hours}시간 {minutes}분 {remaining_seconds}초"
        if minutes:
            return f"{minutes}분 {remaining_seconds}초"
        return f"{remaining_seconds}초"

    def _test_image_matching(self):
        with log_session(self.name):
            if not self.adb_controller:
                messagebox.showerror("오류", "ADB가 연결되지 않았습니다.")
                return
            if self.is_running:
                messagebox.showwarning("경고", "봇이 실행 중일 때는 테스트할 수 없습니다.")
                return

            from tkinter import filedialog

            initial_dir = Path(__file__).parent.parent / "images"
            file_path = filedialog.askopenfilename(
                title="테스트할 이미지 선택",
                initialdir=str(initial_dir),
                filetypes=[
                    ("이미지 파일", "*.png *.PNG *.jpg *.jpeg"),
                    ("모든 파일", "*.*"),
                ],
            )
            if not file_path:
                return

            test_thread = threading.Thread(target=self._run_image_test, args=(file_path,), daemon=True)
            test_thread.start()

    def _run_image_test(self, image_path):
        with log_session(self.name):
            import cv2

            try:
                logger.info("=" * 60)
                logger.info("🔍 이미지 매칭 테스트 시작")
                logger.info("📄 테스트 이미지: %s", Path(image_path).name)
                logger.info("=" * 60)

                screenshot_path = self.runtime_dir / "test_screenshot.png"
                screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                self.adb_controller.screenshot(str(screenshot_path))
                logger.info("📸 스크린샷 저장: %s", screenshot_path)

                screenshot = read_image(str(screenshot_path))
                if screenshot is None:
                    logger.error("❌ 스크린샷을 로드할 수 없습니다.")
                    return

                template = read_image(image_path)
                if template is None:
                    logger.error("❌ 테스트 이미지를 로드할 수 없습니다: %s", image_path)
                    return

                logger.info("✅ 스크린샷 크기: %s", screenshot.shape)
                logger.info("✅ 템플릿 크기: %s", template.shape)
                image_filename = Path(image_path).stem.lower()
                current_threshold = 0.8
                threshold_name = "기본"
                if "mystic_medal" in image_filename:
                    current_threshold = float(self.mystic_medal_threshold.get()) / 100.0
                    threshold_name = "신비의 메달"
                elif "covenant_bookmark" in image_filename:
                    current_threshold = float(self.covenant_bookmark_threshold.get()) / 100.0
                    threshold_name = "성약의 책갈피"
                elif "purchase_button" in image_filename and "disabled" not in image_filename:
                    current_threshold = float(self.purchase_button_threshold.get()) / 100.0
                    threshold_name = "구입 버튼"
                elif "buy_button" in image_filename:
                    current_threshold = float(self.buy_button_threshold.get()) / 100.0
                    threshold_name = "구매 버튼"
                elif "refresh_button" in image_filename or "confirm_button" in image_filename:
                    current_threshold = float(self.refresh_button_threshold.get()) / 100.0
                    threshold_name = "갱신 버튼"

                logger.info("📊 현재 임계값 (%s): %s%%", threshold_name, int(current_threshold * 100))
                result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                logger.info("🔍 다양한 임계값 테스트 결과:")
                for threshold in [0.99, 0.95, 0.92, 0.90, 0.85, 0.80, 0.75, 0.70]:
                    if max_val >= threshold:
                        logger.info("  ✅ 임계값 %s%%: 매칭 성공! (신뢰도: %.4f, 위치: %s)", int(threshold * 100), max_val, max_loc)
                    else:
                        logger.info("  ❌ 임계값 %s%%: 매칭 실패 (최대 신뢰도: %.4f)", int(threshold * 100), max_val)
                logger.info("📈 최대 매칭 신뢰도: %.4f (%s%%)", max_val, int(max_val * 100))
                if max_val >= current_threshold:
                    logger.info("✅ 현재 임계값(%s%%)으로 매칭 성공!", int(current_threshold * 100))
                    logger.info("📍 매칭 위치: %s", max_loc)
                else:
                    recommended = int(max_val * 0.95 * 100)
                    logger.warning("❌ 현재 임계값(%s%%)으로 매칭 실패", int(current_threshold * 100))
                    logger.warning("💡 권장 임계값: %s%% (최대값의 95%%)", recommended)
                logger.info("=" * 60)
            except Exception as e:
                logger.error("테스트 중 오류 발생: %s", e, exc_info=True)

    def log(self, message):
        logger.info(message)


class SecretShopGUI:
    """에픽세븐 비밀상점 봇 GUI"""

    def __init__(self, root):
        self.root = root
        self.root.title("에픽세븐 비밀상점 자동화")
        self.root.geometry("960x800")
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        self.is_closing = False
        self.remote_settings = {}
        self.macro_definitions = [self._default_macro_definition()]

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.sessions = [
            SessionView(self, 1, self.notebook),
            SessionView(self, 2, self.notebook),
        ]
        for session in self.sessions:
            self.notebook.add(session.frame, text=session.name)

        self._setup_logging()
        self._start_settings_update()

    def _setup_logging(self):
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        root_logger.addFilter(SessionContextFilter())

        for session in self.sessions:
            session.add_log_handler()

        log_file = Path("logs") / "bot.log"
        log_file.parent.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.addFilter(SessionContextFilter())
        file_handler.setFormatter(logging.Formatter("%(asctime)s - [%(session_name)s] - %(levelname)s - %(message)s"))
        root_logger.addHandler(file_handler)

    def _default_macro_definition(self):
        return {
            "id": "secret_shop",
            "name": "비밀상점 갱신",
            "description": "신비의 메달과 성약의 책갈피를 찾고 구매합니다.",
            "runner": "secret_shop",
            "steps": [],
        }

    def _start_settings_update(self):
        thread = threading.Thread(target=self._load_settings_update, daemon=True)
        thread.start()

    def _load_settings_update(self):
        updater = RemoteScriptUpdater()
        config, source = updater.load()
        if not config:
            logger.info("자동 설정 업데이트: 기본 내장값을 사용합니다.")
            return
        self.root.after(0, lambda: self._apply_settings_update(config, source))

    def _apply_settings_update(self, config, source):
        if self.is_closing:
            return

        self.remote_settings = config
        macros = config.get("macros", [])
        self.macro_definitions = macros if isinstance(macros, list) and macros else [self._default_macro_definition()]

        gui_config = config.get("gui", {})
        if isinstance(gui_config, dict) and gui_config.get("window_title"):
            self.root.title(gui_config["window_title"])

        for session in self.sessions:
            session.apply_settings_update(config)

        version = config.get("script_version", config.get("config_version", "unknown"))
        logger.info("원격 스크립트 동기화 완료 (%s, 버전: %s)", source, version)

    def is_device_in_use(self, device_id, requester):
        for session in self.sessions:
            if session is requester or not session.adb_controller:
                continue
            if session.adb_controller.device_id == device_id:
                return True
        return False

    def _on_closing(self):
        if self.is_closing:
            return

        running_sessions = [session for session in self.sessions if session.is_running]
        if running_sessions:
            names = ", ".join(session.name for session in running_sessions)
            if not messagebox.askokcancel("종료", f"{names} 매크로가 실행 중입니다. 정말로 종료하시겠습니까?"):
                return
            for session in running_sessions:
                session.request_stop_for_close()

        self.is_closing = True
        self._finish_closing()

    def _finish_closing(self):
        if any(session.bot_thread and session.bot_thread.is_alive() for session in self.sessions):
            self.root.after(300, self._finish_closing)
            return

        for session in self.sessions:
            session.cleanup_on_close()
        self.root.destroy()


def run_gui():
    """GUI 실행"""
    root = tk.Tk()
    SecretShopGUI(root)
    root.mainloop()
