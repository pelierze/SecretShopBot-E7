"""
GUI 인터페이스
tkinter를 사용한 사용자 인터페이스
"""
import os
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import logging
from pathlib import Path

# libpng 경고 메시지 숨기기 (cv2 import 전에 설정)
os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'

from .adb_controller import ADBController
from .remote_script import RemoteScriptUpdater
from .secret_shop_bot import SecretShopBot

logger = logging.getLogger(__name__)


class TextHandler(logging.Handler):
    """로그를 텍스트 위젯에 출력하는 핸들러"""
    
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        
    def emit(self, record):
        msg = self.format(record)
        
        def append():
            # 현재 스크롤 위치 저장
            is_at_bottom = self.text_widget.yview()[1] >= 0.99
            
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, msg + '\n')
            self.text_widget.configure(state='disabled')
            
            # 맨 아래에 있었을 때만 자동 스크롤
            if is_at_bottom:
                self.text_widget.yview(tk.END)
            
        self.text_widget.after(0, append)


class SecretShopGUI:
    """에픽세븐 비밀상점 봇 GUI"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("에픽세븐 비밀상점 자동화")
        self.root.geometry("900x750")
        self.root.resizable(True, True)
        
        # 윈도우 종료 시 ADB 정리
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        # 변수
        self.adb_controller = None
        self.bot = None
        self.is_running = False
        self.is_closing = False
        self.bot_thread = None
        self.adb_server_started = False
        self.remote_settings = {}
        
        # UI 생성
        self._create_widgets()
        
        # 로깅 설정
        self._setup_logging()
        self._start_settings_update()
        
    def _create_widgets(self):
        """UI 위젯 생성"""
        
        # === ADB 연결 섹션 ===
        self.connection_frame = ttk.LabelFrame(self.root, text="ADB 연결", padding=10)
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
        
        self.disconnect_btn = ttk.Button(self.connection_frame, text="연결 해제", command=self._disconnect_adb, state=tk.DISABLED)
        self.disconnect_btn.grid(row=0, column=6, padx=5)
        
        self.connection_status = ttk.Label(self.connection_frame, text="● 연결 안됨", foreground="red")
        self.connection_status.grid(row=0, column=7, padx=10)
        
        # 장치 목록
        self.device_label = ttk.Label(self.connection_frame, text="장치:")
        self.device_label.grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.device_combo = ttk.Combobox(self.connection_frame, width=30, state="readonly")
        self.device_combo.grid(row=1, column=1, columnspan=4, sticky=tk.W, padx=5, pady=5)
        self.device_combo.bind("<<ComboboxSelected>>", self._on_device_selected)
        
        # === 설정 섹션 ===
        self.settings_frame = ttk.LabelFrame(self.root, text="매크로 설정", padding=10)
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
        
        # 이미지별 매칭 임계값 설정
        self.threshold_header_label = ttk.Label(self.settings_frame, text="=== 이미지 매칭 정확도 (70-99) ===", font=("Arial", 9, "bold"))
        self.threshold_header_label.grid(row=2, column=0, columnspan=3, sticky=tk.W, padx=5, pady=(10, 5))
        
        # 아이템 임계값
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
        
        # 버튼 임계값
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
        
        # 디버그 모드 체크박스
        self.debug_mode_var = tk.BooleanVar(value=False)
        self.debug_checkbox = ttk.Checkbutton(self.settings_frame, text="디버그 모드 (상세 로그)", variable=self.debug_mode_var)
        self.debug_checkbox.grid(row=8, column=0, columnspan=2, sticky=tk.W, padx=5, pady=5)
        
        # === 제어 섹션 ===
        control_frame = ttk.Frame(self.root, padding=10)
        control_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.start_btn = ttk.Button(control_frame, text="▶ 시작", command=self._start_bot, state=tk.DISABLED)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.pause_btn = ttk.Button(control_frame, text="⏸ 일시정지", command=self._pause_bot, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=5)
        
        self.resume_btn = ttk.Button(control_frame, text="▶ 재개", command=self._resume_bot, state=tk.DISABLED)
        self.resume_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = ttk.Button(control_frame, text="■ 중지", command=self._stop_bot, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        # 이미지 매칭 테스트 버튼
        self.test_btn = ttk.Button(control_frame, text="💡 이미지 테스트", command=self._test_image_matching, state=tk.DISABLED)
        self.test_btn.pack(side=tk.LEFT, padx=5)
        
        # 일시정지 상태 표시
        self.pause_label = ttk.Label(control_frame, text="", foreground="orange", font=("Arial", 10, "bold"))
        self.pause_label.pack(side=tk.LEFT, padx=10)
        
        # === 통계 섹션 ===
        self.stats_frame = ttk.LabelFrame(self.root, text="통계", padding=10)
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
        
        # === 로그 섹션 ===
        self.log_frame = ttk.LabelFrame(self.root, text="로그", padding=10)
        self.log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(self.log_frame, state='disabled', height=25, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
    def _setup_logging(self):
        """로깅 설정"""
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        
        # 기존 핸들러 제거
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # 텍스트 위젯 핸들러 추가
        text_handler = TextHandler(self.log_text)
        text_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(text_handler)
        
        # 파일 핸들러 추가
        log_file = Path("logs") / "bot.log"
        log_file.parent.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)

    def _start_settings_update(self):
        """원격 설정 업데이트를 백그라운드에서 확인합니다."""
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
        """검증된 원격 스크립트를 UI 기본값과 실행 설정에 반영합니다."""
        if self.is_running or self.is_closing:
            return

        self.remote_settings = config
        self._apply_remote_gui(config.get("gui", {}))

        defaults = config.get("defaults", {})
        thresholds = config.get("thresholds", {})

        def replace_entry(entry, value):
            entry.delete(0, tk.END)
            entry.insert(0, str(value))

        if "refresh_count" in defaults:
            replace_entry(self.refresh_count_entry, defaults["refresh_count"])
        if "purchase_verification_count" in defaults:
            replace_entry(self.buy_count_entry, defaults["purchase_verification_count"])

        threshold_entries = {
            "mystic_medal": self.mystic_medal_threshold,
            "covenant_bookmark": self.covenant_bookmark_threshold,
            "purchase_button": self.purchase_button_threshold,
            "buy_button": self.buy_button_threshold,
            "refresh_button": self.refresh_button_threshold,
        }
        for key, entry in threshold_entries.items():
            if key in thresholds:
                replace_entry(entry, thresholds[key])

        version = config.get("script_version", config.get("config_version", "unknown"))
        logger.info(f"원격 스크립트 동기화 완료 ({source}, 버전: {version})")

    def _apply_remote_gui(self, gui_config):
        """원격 GUI 정의 중 현재 클라이언트가 지원하는 항목만 적용합니다."""
        if not isinstance(gui_config, dict):
            return

        if gui_config.get("window_title"):
            self.root.title(gui_config["window_title"])

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
        
    def _scan_devices(self):
        """장치 검색"""
        try:
            from .adb_controller import ADBController
            
            # 임시 ADB 컨트롤러 생성
            temp_adb = ADBController()
            self.adb_server_started = True
            try:
                devices = temp_adb.get_devices()
            finally:
                if self.adb_controller is None:
                    temp_adb.kill_server()
            
            if not devices:
                logger.warning("⚠️ 연결된 장치가 없습니다. ADB 디버깅이 활성화되어 있는지 확인하세요.")
                self.device_combo['values'] = []
                return
            
            # 장치 목록 업데이트
            device_list = [f"{d['id']} ({d['status']})" for d in devices]
            self.device_combo['values'] = device_list
            
            if device_list:
                self.device_combo.current(0)  # 첫 번째 장치 선택
                self._on_device_selected(None)
            
            logger.info(f"🔍 장치 {len(devices)}개 발견: {[d['id'] for d in devices]}")
            
        except Exception as e:
            logger.error(f"장치 검색 중 오류: {e}")
    
    def _on_device_selected(self, event):
        """장치 선택 시 호출"""
        if self.device_combo.get():
            # 선택된 장치 ID 추출 ("device_id (status)" 형식)
            device_str = self.device_combo.get()
            device_id = device_str.split(' (')[0]
            
            # IP와 포트로 분리
            if ':' in device_id:
                parts = device_id.split(':')
                self.ip_entry.delete(0, tk.END)
                self.ip_entry.insert(0, parts[0])
                self.port_entry.delete(0, tk.END)
                self.port_entry.insert(0, parts[1])
    
    def log(self, message):
        """로그 메시지 출력 (logging을 통해)"""
        logger.info(message)
    
    def _connect_adb(self):
        """ADB 연결"""
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
        
        self.adb_controller = ADBController()
        
        if self.adb_controller.connect(ip, port):
            self.adb_server_started = True
            self.connection_status.config(text="● 연결됨", foreground="green")
            self.start_btn.config(state=tk.NORMAL)
            self.test_btn.config(state=tk.NORMAL)
            self.connect_btn.config(state=tk.DISABLED)
            self.disconnect_btn.config(state=tk.NORMAL)
            logger.info(f"✅ ADB 연결 성공: {ip}:{port}")
        else:
            self.connection_status.config(text="● 연결 실패", foreground="red")
            logger.error(f"❌ ADB 연결 실패: {ip}:{port} - 앱플레이어가 실행 중인지 확인하세요")
            
    def _start_bot(self):
        """봇 시작"""
        if self.is_running:
            return
        
        # 설정값 검증
        try:
            refresh_count = int(self.refresh_count_entry.get())
            buy_count = int(self.buy_count_entry.get())
            
            # 이미지별 임계값 가져오기
            thresholds = {
                key: int(value) / 100.0
                for key, value in self.remote_settings.get("thresholds", {}).items()
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
            messagebox.showerror("오류", f"설정값이 올바르지 않습니다.\n{str(e)}\n리프레시 횟수와 구매 횟수는 양수여야 하며,\n매칭 정확도는 70~99 사이여야 합니다.")
            return
        
        # 봇 생성 (이미지별 임계값 및 디버그 모드 전달)
        debug_mode = self.debug_mode_var.get()
        self.bot = SecretShopBot(
            self.adb_controller,
            thresholds=thresholds,
            debug_mode=debug_mode,
            automation_settings=self.remote_settings,
        )
        
        # UI 상태 변경
        self.is_running = True
        self.start_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.NORMAL)
        self.resume_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.connect_btn.config(state=tk.DISABLED)
        self.disconnect_btn.config(state=tk.DISABLED)
        
        # 설정 필드 비활성화
        self.refresh_count_entry.config(state=tk.DISABLED)
        self.buy_count_entry.config(state=tk.DISABLED)
        self.mystic_medal_threshold.config(state=tk.DISABLED)
        self.covenant_bookmark_threshold.config(state=tk.DISABLED)
        self.purchase_button_threshold.config(state=tk.DISABLED)
        self.buy_button_threshold.config(state=tk.DISABLED)
        self.refresh_button_threshold.config(state=tk.DISABLED)
        self.debug_checkbox.config(state=tk.DISABLED)
        
        # 통계 초기화
        self._update_stats({
            "total_refreshes": 0,
            "completed_runs": 0,
            "successful_refreshes": 0,
            "mystic_medal_bought": 0,
            "covenant_bookmark_bought": 0
        })
        
        # 별도 스레드에서 봇 실행
        self.bot_thread = threading.Thread(target=self._run_bot, args=(refresh_count, buy_count), daemon=True)
        self.bot_thread.start()
        
    def _run_bot(self, refresh_count, buy_count):
        """봇 실행 (별도 스레드)"""
        try:
            # 정기적으로 통계 업데이트 및 일시정지 상태 확인
            def update_stats_and_check_pause():
                if self.is_running and self.bot:
                    stats = self.bot.get_stats()
                    self._update_stats(stats)
                    
                    # 일시정지 상태 표시
                    if self.bot.paused:
                        self.pause_label.config(text="⏸️  일시정지 중")
                        self.pause_btn.config(state=tk.DISABLED)
                        self.resume_btn.config(state=tk.NORMAL)
                    else:
                        self.pause_label.config(text="")
                        self.pause_btn.config(state=tk.NORMAL)
                        self.resume_btn.config(state=tk.DISABLED)
                    
                    self.root.after(500, update_stats_and_check_pause)
            
            self.root.after(500, update_stats_and_check_pause)
            
            # 봇 실행
            final_stats = self.bot.run(refresh_count, buy_count)
            
            # 최종 통계 업데이트
            self._update_stats(final_stats)
            
            # 완료 메시지
            completion_msg = self._format_stats_summary("✅ 자동화 완료", final_stats)
            self.log(completion_msg)
            
        except Exception as e:
            logging.error(f"봇 실행 중 오류: {e}", exc_info=True)
            if not self.is_closing:
                self.root.after(0, lambda: messagebox.showerror("오류", f"실행 중 오류 발생:\n{str(e)}"))
        
        finally:
            self.is_running = False
            if not self.is_closing:
                self.root.after(0, self._reset_ui)
            
    def _pause_bot(self):
        """봇 일시정지"""
        if self.bot:
            self.bot.set_user_action('pause')
            self.log("⏸️ 일시정지 요청됨")
            # 즉시 UI 업데이트
            self.pause_label.config(text="⏸️  일시정지 중")
            self.pause_btn.config(state=tk.DISABLED)
            self.resume_btn.config(state=tk.NORMAL)
    
    def _resume_bot(self):
        """봇 재개"""
        if self.bot:
            self.bot.set_user_action('resume')
            self.log("▶️ 재개 요청됨")
            # 즉시 UI 업데이트
            self.pause_label.config(text="")
            self.pause_btn.config(state=tk.NORMAL)
            self.resume_btn.config(state=tk.DISABLED)
    
    def _stop_bot(self):
        """봇 중지"""
        if not self.is_running:
            return
        
        if self.bot:
            self.bot.set_user_action('stop')
        
        self.is_running = False
        
        # 현재 통계 가져오기
        if self.bot:
            stats = self.bot.get_stats()
            
            if stats.get('total_refreshes', 0) > 0:
                stop_msg = (
                    self._format_stats_summary("⛔ 자동화 중지", stats)
                )
                self.log(stop_msg)
            else:
                self.log("⛔ 봇이 중지되었습니다.")
        else:
            self.log("⛔ 봇이 중지되었습니다.")
        
    def _update_stats(self, stats):
        """통계 업데이트"""
        completed_runs = stats.get("completed_runs", stats.get("total_refreshes", 0))
        self.total_refresh_label.config(text=str(completed_runs))
        self.mystic_label.config(text=str(stats.get("mystic_medal_bought", 0)))
        self.bookmark_label.config(text=str(stats.get("covenant_bookmark_bought", 0)))
        
        # 경과 시간 업데이트
        import time
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
        """완료/중지 통계를 읽기 쉬운 로그 메시지로 만듭니다."""
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
        
    def _disconnect_adb(self):
        """ADB 연결 해제"""
        if self.is_running:
            messagebox.showwarning("경고", "봇이 실행 중일 때는 연결을 해제할 수 없습니다.")
            return
        
        if self.adb_controller:
            # 현재 디바이스 연결만 해제하고, 서버 종료는 프로그램 종료 시 처리
            self.adb_controller.disconnect()
            self.adb_controller = None
        
        self.connection_status.config(text="● 연결 안됨", foreground="red")
        self.start_btn.config(state=tk.DISABLED)
        self.test_btn.config(state=tk.DISABLED)
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED)
        self.log("✅ ADB 연결이 해제되었습니다.")
    
    def _on_closing(self):
        """프로그램 종료 시 처리"""
        if self.is_closing:
            return

        if self.is_running:
            if messagebox.askokcancel("종료", "매크로가 실행 중입니다. 정말로 종료하시겠습니까?"):
                # 봇 중지
                if self.bot:
                    self.bot.set_user_action('stop')
                self.is_running = False
            else:
                return
        
        self.is_closing = True
        self._finish_closing()

    def _finish_closing(self):
        """봇 스레드가 정리될 시간을 조금 준 뒤 프로그램을 종료합니다."""
        if self.bot_thread and self.bot_thread.is_alive():
            self.root.after(300, self._finish_closing)
            return

        self._cleanup_adb_server()
        self.root.destroy()

    def _cleanup_adb_server(self):
        """이 앱이 사용한 ADB 서버를 종료합니다."""
        if self.adb_controller:
            logger.info("프로그램 종료 - ADB 서버 종료 중...")
            self.adb_controller.kill_server()
            self.adb_controller = None
        elif self.adb_server_started:
            try:
                cleanup_adb = ADBController()
                cleanup_adb.kill_server()
            except Exception as e:
                logger.error(f"ADB 서버 종료 중 오류: {e}")
    
    def _reset_ui(self):
        """상태 복귀"""
        self.start_btn.config(state=tk.NORMAL if self.adb_controller else tk.DISABLED)
        self.test_btn.config(state=tk.NORMAL if self.adb_controller else tk.DISABLED)
        self.pause_btn.config(state=tk.DISABLED)
        self.resume_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)
        self.connect_btn.config(state=tk.DISABLED if self.adb_controller else tk.NORMAL)
        self.disconnect_btn.config(state=tk.NORMAL if self.adb_controller else tk.DISABLED)
        self.pause_label.config(text="")
        
        # 설정 필드 활성화
        self.refresh_count_entry.config(state=tk.NORMAL)
        self.buy_count_entry.config(state=tk.NORMAL)
        self.mystic_medal_threshold.config(state=tk.NORMAL)
        self.covenant_bookmark_threshold.config(state=tk.NORMAL)
        self.purchase_button_threshold.config(state=tk.NORMAL)
        self.buy_button_threshold.config(state=tk.NORMAL)
        self.refresh_button_threshold.config(state=tk.NORMAL)
        self.debug_checkbox.config(state=tk.NORMAL)
    
    def _test_image_matching(self):
        """이미지 매칭 테스트"""
        if not self.adb_controller:
            messagebox.showerror("오류", "ADB가 연결되지 않았습니다.")
            return
        
        if self.is_running:
            messagebox.showwarning("경고", "봇이 실행 중일 때는 테스트할 수 없습니다.")
            return
        
        # 파일 선택 대화상자
        from tkinter import filedialog
        
        base_dir = Path(__file__).parent.parent
        initial_dir = base_dir / "images"
        
        file_path = filedialog.askopenfilename(
            title="테스트할 이미지 선택",
            initialdir=str(initial_dir),
            filetypes=[
                ("이미지 파일", "*.png *.PNG *.jpg *.jpeg"),
                ("모든 파일", "*.*")
            ]
        )
        
        if not file_path:
            return  # 사용자가 취소함
        
        # 별도 스레드에서 테스트 실행
        test_thread = threading.Thread(target=self._run_image_test, args=(file_path,), daemon=True)
        test_thread.start()
    
    def _run_image_test(self, image_path):
        """이미지 매칭 테스트 실행"""
        import cv2
        import numpy as np
        
        try:
            logging.info("="*60)
            logging.info("🔍 이미지 매칭 테스트 시작")
            logging.info(f"📄 테스트 이미지: {Path(image_path).name}")
            logging.info("="*60)
            
            # 현재 화면 스크린샷
            base_dir = Path(__file__).parent.parent
            screenshot_path = base_dir / "logs" / "test_screenshot.png"
            screenshot_path.parent.mkdir(exist_ok=True)
            
            self.adb_controller.screenshot(str(screenshot_path))
            logging.info(f"📸 스크린샷 저장: {screenshot_path}")
            
            screenshot = cv2.imread(str(screenshot_path))
            if screenshot is None:
                logging.error("❌ 스크린샷을 로드할 수 없습니다.")
                return
            
            # 테스트 이미지 로드
            template = cv2.imread(image_path)
            if template is None:
                logging.error(f"❌ 테스트 이미지를 로드할 수 없습니다: {image_path}")
                return
            
            logging.info(f"✅ 스크린샷 크기: {screenshot.shape}")
            logging.info(f"✅ 템플릿 크기: {template.shape}")
            logging.info("")
            
            # 이미지 파일명에 따른 임계값 가져오기
            image_filename = Path(image_path).stem.lower()
            current_threshold = 0.8  # 기본값
            
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
            else:
                threshold_name = "기본"
            
            logging.info(f"📊 현재 임계값 ({threshold_name}): {int(current_threshold*100)}%")
            logging.info("")
            
            # 다양한 임계값으로 테스트
            thresholds = [0.99, 0.95, 0.92, 0.90, 0.85, 0.80, 0.75, 0.70]
            
            result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            
            logging.info("🔍 다양한 임계값 테스트 결과:")
            for threshold in thresholds:
                if max_val >= threshold:
                    logging.info(f"  ✅ 임계값 {int(threshold*100)}%: 매칭 성공! (신뢰도: {max_val:.4f}, 위치: {max_loc})")
                else:
                    logging.info(f"  ❌ 임계값 {int(threshold*100)}%: 매칭 실패 (최대 신뢰도: {max_val:.4f})")
            
            logging.info("")
            logging.info("="*60)
            logging.info(f"📈 최대 매칭 신뢰도: {max_val:.4f} ({int(max_val*100)}%)")
            
            if max_val >= current_threshold:
                logging.info(f"✅ 현재 임계값({int(current_threshold*100)}%)으로 매칭 성공!")
                logging.info(f"📍 매칭 위치: {max_loc}")
            else:
                recommended = int(max_val * 0.95 * 100)
                logging.warning(f"❌ 현재 임계값({int(current_threshold*100)}%)으로 매칭 실패")
                logging.warning(f"💡 권장 임계값: {recommended}% (최대값의 95%)")
            
            logging.info("="*60)
            
        except Exception as e:
            logging.error(f"테스트 중 오류 발생: {e}", exc_info=True)


def run_gui():
    """GUI 실행"""
    root = tk.Tk()
    app = SecretShopGUI(root)
    root.mainloop()
