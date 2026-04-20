"""
GUI 인터페이스
tkinter를 사용한 사용자 인터페이스
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import logging
from pathlib import Path

from .adb_controller import ADBController
from .secret_shop_bot import SecretShopBot


class TextHandler(logging.Handler):
    """로그를 텍스트 위젯에 출력하는 핸들러"""
    
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        
    def emit(self, record):
        msg = self.format(record)
        
        def append():
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, msg + '\n')
            self.text_widget.configure(state='disabled')
            self.text_widget.yview(tk.END)
            
        self.text_widget.after(0, append)


class SecretShopGUI:
    """에픽세븐 비밀상점 봇 GUI"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("에픽세븐 비밀상점 자동화")
        self.root.geometry("700x600")
        self.root.resizable(False, False)
        
        # 변수
        self.adb_controller = None
        self.bot = None
        self.is_running = False
        
        # UI 생성
        self._create_widgets()
        
        # 로깅 설정
        self._setup_logging()
        
    def _create_widgets(self):
        """UI 위젯 생성"""
        
        # === ADB 연결 섹션 ===
        connection_frame = ttk.LabelFrame(self.root, text="ADB 연결", padding=10)
        connection_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(connection_frame, text="IP 주소:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.ip_entry = ttk.Entry(connection_frame, width=15)
        self.ip_entry.insert(0, "127.0.0.1")
        self.ip_entry.grid(row=0, column=1, padx=5)
        
        ttk.Label(connection_frame, text="포트:").grid(row=0, column=2, sticky=tk.W, padx=5)
        self.port_entry = ttk.Entry(connection_frame, width=8)
        self.port_entry.insert(0, "5555")
        self.port_entry.grid(row=0, column=3, padx=5)
        
        self.connect_btn = ttk.Button(connection_frame, text="연결", command=self._connect_adb)
        self.connect_btn.grid(row=0, column=4, padx=5)
        
        self.disconnect_btn = ttk.Button(connection_frame, text="연결 해제", command=self._disconnect_adb, state=tk.DISABLED)
        self.disconnect_btn.grid(row=0, column=5, padx=5)
        
        self.connection_status = ttk.Label(connection_frame, text="● 연결 안됨", foreground="red")
        self.connection_status.grid(row=0, column=6, padx=10)
        
        # === 설정 섹션 ===
        settings_frame = ttk.LabelFrame(self.root, text="매크로 설정", padding=10)
        settings_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(settings_frame, text="리프레시 횟수:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.refresh_count_entry = ttk.Entry(settings_frame, width=10)
        self.refresh_count_entry.insert(0, "100")
        self.refresh_count_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        ttk.Label(settings_frame, text="회").grid(row=0, column=2, sticky=tk.W)
        
        ttk.Label(settings_frame, text="발견된 아이템 구매 개수:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.buy_count_entry = ttk.Entry(settings_frame, width=10)
        self.buy_count_entry.insert(0, "1")
        self.buy_count_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        ttk.Label(settings_frame, text="개 (같은 아이템을 여러 번 구매)").grid(row=1, column=2, sticky=tk.W)
        
        ttk.Label(settings_frame, text="이미지 매칭 정확도:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.threshold_scale = ttk.Scale(settings_frame, from_=0.7, to=0.99, orient=tk.HORIZONTAL, length=150)
        self.threshold_scale.set(0.92)  # 기본값 92%
        self.threshold_scale.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        self.threshold_label = ttk.Label(settings_frame, text="92%")
        self.threshold_label.grid(row=2, column=2, sticky=tk.W, padx=5)
        
        # 슬라이더 값 변경 시 레이블 업데이트
        def update_threshold_label(val):
            threshold_percent = int(float(val) * 100)
            self.threshold_label.config(text=f"{threshold_percent}%")
        self.threshold_scale.config(command=update_threshold_label)
        
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
        stats_frame = ttk.LabelFrame(self.root, text="통계", padding=10)
        stats_frame.pack(fill=tk.X, padx=10, pady=5)
        
        stats_grid = ttk.Frame(stats_frame)
        stats_grid.pack(fill=tk.X)
        
        ttk.Label(stats_grid, text="총 리프레시:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.total_refresh_label = ttk.Label(stats_grid, text="0", foreground="blue", font=("Arial", 10, "bold"))
        self.total_refresh_label.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        
        ttk.Label(stats_grid, text="신비의 메달:").grid(row=0, column=2, sticky=tk.W, padx=5, pady=2)
        self.mystic_label = ttk.Label(stats_grid, text="0", foreground="blue", font=("Arial", 10, "bold"))
        self.mystic_label.grid(row=0, column=3, sticky=tk.W, padx=5, pady=2)
        
        ttk.Label(stats_grid, text="성약의 책갈피:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.bookmark_label = ttk.Label(stats_grid, text="0", foreground="blue", font=("Arial", 10, "bold"))
        self.bookmark_label.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        
        # === 로그 섹션 ===
        log_frame = ttk.LabelFrame(self.root, text="로그", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, state='disabled', height=15, wrap=tk.WORD)
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
            self.connection_status.config(text="● 연결됨", foreground="green")
            self.start_btn.config(state=tk.NORMAL)
            self.test_btn.config(state=tk.NORMAL)
            self.connect_btn.config(state=tk.DISABLED)
            self.disconnect_btn.config(state=tk.NORMAL)
            messagebox.showinfo("성공", f"ADB 연결 성공: {ip}:{port}")
        else:
            self.connection_status.config(text="● 연결 실패", foreground="red")
            messagebox.showerror("오류", "ADB 연결에 실패했습니다.\n앱플레이어가 실행 중인지 확인하세요.")
            
    def _start_bot(self):
        """봇 시작"""
        if self.is_running:
            return
        
        # 설정값 검증
        try:
            refresh_count = int(self.refresh_count_entry.get())
            buy_count = int(self.buy_count_entry.get())
            match_threshold = float(self.threshold_scale.get())
            
            if refresh_count <= 0 or buy_count <= 0:
                raise ValueError()
            if not 0.0 <= match_threshold <= 1.0:
                raise ValueError()
        except ValueError:
            messagebox.showerror("오류", "설정값이 올바르지 않습니다.\n리프레시 횟수와 구매 횟수는 양수여야 하며,\n매칭 정확도는 0~1 사이여야 합니다.")
            return
        
        # 봇 생성 (매칭 임계값 전달)
        self.bot = SecretShopBot(self.adb_controller, match_threshold=match_threshold)
        
        # UI 상태 변경
        self.is_running = True
        self.start_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.NORMAL)
        self.resume_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.connect_btn.config(state=tk.DISABLED)
        
        # 통계 초기화
        self._update_stats({
            "total_refreshes": 0,
            "mystic_medal_bought": 0,
            "covenant_bookmark_bought": 0
        })
        
        # 별도 스레드에서 봇 실행
        bot_thread = threading.Thread(target=self._run_bot, args=(refresh_count, buy_count), daemon=True)
        bot_thread.start()
        
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
            self.root.after(0, lambda: messagebox.showinfo(
                "완료",
                f"자동화가 완료되었습니다!\n\n"
                f"총 리프레시: {final_stats['total_refreshes']}회\n"
                f"신비의 메달: {final_stats['mystic_medal_bought']}개\n"
                f"성약의 책갈피: {final_stats['covenant_bookmark_bought']}개"
            ))
            
        except Exception as e:
            logging.error(f"봇 실행 중 오류: {e}", exc_info=True)
            self.root.after(0, lambda: messagebox.showerror("오류", f"실행 중 오류 발생:\n{str(e)}"))
        
        finally:
            self.is_running = False
            self.root.after(0, self._reset_ui)
            
    def _pause_bot(self):
        """봇 일시정지"""
        if self.bot:
            self.bot.set_user_action('pause')
    
    def _resume_bot(self):
        """봇 재개"""
        if self.bot:
            self.bot.set_user_action('resume')
    
    def _stop_bot(self):
        """봇 중지"""
        if not self.is_running:
            return
        
        if self.bot:
            self.bot.set_user_action('stop')
        
        self.is_running = False
        messagebox.showinfo("중지", "봇이 중지됩니다.")
        
    def _update_stats(self, stats):
        """통계 업데이트"""
        self.total_refresh_label.config(text=str(stats.get("total_refreshes", 0)))
        self.mystic_label.config(text=str(stats.get("mystic_medal_bought", 0)))
        self.bookmark_label.config(text=str(stats.get("covenant_bookmark_bought", 0)))
        
    def _disconnect_adb(self):
        """ADB 연결 해제"""
        if self.is_running:
            messagebox.showwarning("경고", "봇이 실행 중일 때는 연결을 해제할 수 없습니다.")
            return
        
        if self.adb_controller:
            self.adb_controller = None
        
        self.connection_status.config(text="● 연결 안됨", foreground="red")
        self.start_btn.config(state=tk.DISABLED)
        self.test_btn.config(state=tk.DISABLED)
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED)
        messagebox.showinfo("성공", "ADB 연결이 해제되었습니다.")
    
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
    
    def _test_image_matching(self):
        """이미지 매칭 테스트"""
        if not self.adb_controller:
            messagebox.showerror("오류", "ADB가 연결되지 않았습니다.")
            return
        
        if self.is_running:
            messagebox.showwarning("경고", "봇이 실행 중일 때는 테스트할 수 없습니다.")
            return
        
        # 별도 스레드에서 테스트 실행
        test_thread = threading.Thread(target=self._run_image_test, daemon=True)
        test_thread.start()
    
    def _run_image_test(self):
        """이미지 매칭 테스트 실행"""
        import cv2
        import numpy as np
        
        try:
            logging.info("="*60)
            logging.info("🔍 이미지 매칭 테스트 시작")
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
            
            # 테스트할 이미지 목록
            items_dir = base_dir / "images" / "items"
            buttons_dir = base_dir / "images" / "buttons"
            
            test_images = []
            
            # 아이템 이미지
            if items_dir.exists():
                for img_file in items_dir.glob("*.png"):
                    test_images.append(("아이템", img_file))
                for img_file in items_dir.glob("*.PNG"):
                    test_images.append(("아이템", img_file))
            
            # 버튼 이미지
            if buttons_dir.exists():
                for img_file in buttons_dir.glob("*.png"):
                    test_images.append(("버튼", img_file))
                for img_file in buttons_dir.glob("*.PNG"):
                    test_images.append(("버튼", img_file))
            
            if not test_images:
                logging.warning("⚠️  테스트할 이미지가 없습니다.")
                return
            
            # 현재 설정된 임계값
            current_threshold = float(self.threshold_scale.get())
            
            logging.info(f"📊 현재 임계값: {int(current_threshold*100)}%")
            logging.info(f"🔍 테스트 이미지 개수: {len(test_images)}")
            logging.info("")
            
            # 각 이미지 테스트
            for img_type, img_path in test_images:
                template = cv2.imread(str(img_path))
                if template is None:
                    logging.warning(f"⚠️  [{img_type}] {img_path.name}: 이미지 로드 실패")
                    continue
                
                # 매칭 수행
                result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                
                # 결과 출력
                confidence_percent = int(max_val * 100)
                
                if max_val >= current_threshold:
                    logging.info(f"✅ [{img_type}] {img_path.name}: {confidence_percent}% (위치: {max_loc})")
                else:
                    # 권장 임계값 계산
                    recommended = int(max_val * 0.95 * 100)
                    logging.warning(f"❌ [{img_type}] {img_path.name}: {confidence_percent}% (현재 임계값: {int(current_threshold*100)}%, 권장: {recommended}%)")
            
            logging.info("")
            logging.info("="*60)
            logging.info("✅ 이미지 매칭 테스트 완료")
            logging.info("💡 매칭 실패한 이미지는 임계값을 낮추거나 이미지를 다시 캡처하세요.")
            logging.info("="*60)
            
        except Exception as e:
            logging.error(f"테스트 중 오류 발생: {e}", exc_info=True)


def run_gui():
    """GUI 실행"""
    root = tk.Tk()
    app = SecretShopGUI(root)
    root.mainloop()
