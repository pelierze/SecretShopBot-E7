"""Show release notes before asking the user to install an update."""
import tkinter as tk
from tkinter import ttk, simpledialog, scrolledtext


class UpdateConfirmationDialog(simpledialog.Dialog):
    def __init__(self, parent, release, current_version, open_release_page):
        self.release = release
        self.current_version = current_version
        self.open_release_page = open_release_page
        self.confirmed = False
        super().__init__(parent, title='업데이트 안내')

    def body(self, master):
        ttk.Label(master, text=f'현재 v{self.current_version} → 새 버전 {self.release.version}',
                  font=('맑은 고딕', 11, 'bold')).pack(anchor=tk.W, padx=8, pady=(8, 10))
        ttk.Label(master, text='이번 버전에서 달라진 점').pack(anchor=tk.W, padx=8)
        self.notes = scrolledtext.ScrolledText(master, width=64, height=14,
                                              wrap=tk.WORD, font=('맑은 고딕', 10))
        self.notes.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        # Display remote Markdown as text, without HTML or executable content.
        self.notes.insert('1.0', self.release.body.strip() or '이 버전의 릴리즈 노트가 등록되지 않았습니다.')
        self.notes.configure(state=tk.DISABLED)
        ttk.Label(master, text='다운로드가 끝나면 실행 중인 봇을 중지합니다.\n'
                  '설정과 로그는 유지되며 봇은 자동 재개하지 않습니다.',
                  justify=tk.LEFT).pack(anchor=tk.W, padx=8, pady=(4, 8))

    def buttonbox(self):
        buttons = ttk.Frame(self)
        buttons.pack(fill=tk.X, padx=16, pady=(0, 12))
        ttk.Button(buttons, text='릴리즈 페이지', command=self.open_release_page).pack(side=tk.LEFT)
        ttk.Button(buttons, text='나중에', command=self.cancel).pack(side=tk.RIGHT, padx=(8, 0))
        self.install_button = ttk.Button(buttons, text='업데이트 후 재시작', command=self.ok)
        self.install_button.pack(side=tk.RIGHT)
        self.bind('<Escape>', self.cancel)

    def apply(self):
        self.confirmed = True
