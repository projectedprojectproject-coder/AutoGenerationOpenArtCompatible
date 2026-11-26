#!/usr/bin/env python3
"""Shorts Maker -- windowed app (Tkinter, stdlib only) wrapping the shorts-pipeline.

Run directly for development:
    uv run tools/shorts_gui.py

Packaged as an .exe with PyInstaller (see build-exe.ps1):
    uv run --with pyinstaller pyinstaller --onefile --windowed --name "Shorts Maker" tools/shorts_gui.py

A frozen build is expected to sit at the toolkit root (next to pyproject.toml,
.claude/, shorts-jobs/, ...), same convention as the .bat launchers.
"""
from __future__ import annotations

import queue
import shutil
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).parent))
from win_encoding import ensure_utf8_output  # noqa: E402
from shorts_common import (  # noqa: E402
    build_pipeline_prompt,
    check_claude_auth,
    check_higgsfield_mcp,
    check_toolchain_status,
    check_youtube,
    connect_higgsfield_mcp,
    ensure_full_toolchain,
    find_final_mp4,
    get_env_var,
    login_claude_cli,
    new_job_id,
    refresh_path_from_registry,
    run_claude_headless,
    set_env_var,
    slugify,
    verify_job_topic,
)


class ShortsMakerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Shorts Maker")
        self.geometry("720x640")
        self.minsize(640, 560)

        self._worker: threading.Thread | None = None
        self._log_queue: "queue.Queue[str]" = queue.Queue()
        self._install_log_queue: "queue.Queue[str]" = queue.Queue()
        self._installing_claude = False
        self._cancel_requested = False

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.install_tab = ttk.Frame(notebook)
        self.run_tab = ttk.Frame(notebook)
        notebook.add(self.install_tab, text="설치")
        notebook.add(self.run_tab, text="실행")

        self._build_install_tab()
        self._build_run_tab()
        self.after(150, self._drain_log_queue)
        self.after(150, self._drain_install_log_queue)
        self.after(300, self._refresh_status)

    # ------------------------------------------------------------------
    # 설치 탭
    # ------------------------------------------------------------------

    def _build_install_tab(self) -> None:
        f = self.install_tab
        pad = {"padx": 10, "pady": 6}

        r = 0

        ttk.Label(f, text="음성 생성 서비스 (ElevenLabs)", font=("", 10, "bold")).grid(row=r, column=0, columnspan=2, sticky="w", **pad)
        self.eleven_mode_var = tk.StringVar(value="api")
        ttk.Radiobutton(f, text="API 키", variable=self.eleven_mode_var, value="api",
                        command=self._toggle_eleven_mode).grid(row=r, column=2, sticky="w", **pad)
        ttk.Radiobutton(f, text="Claude Code MCP", variable=self.eleven_mode_var, value="mcp",
                        command=self._toggle_eleven_mode).grid(row=r, column=3, sticky="w", **pad)
        r += 1

        self.eleven_api_frame = ttk.Frame(f)
        self.eleven_api_frame.grid(row=r, column=0, columnspan=4, sticky="w", padx=10)
        ttk.Label(self.eleven_api_frame, text="API 키").grid(row=0, column=0, sticky="w", padx=4)
        self.eleven_key_var = tk.StringVar()
        ttk.Entry(self.eleven_api_frame, textvariable=self.eleven_key_var, show="*", width=30).grid(row=0, column=1, padx=4)
        ttk.Button(self.eleven_api_frame, text="저장", command=self._save_eleven_key).grid(row=0, column=2, padx=6)
        self.eleven_status = ttk.Label(self.eleven_api_frame, text="확인 중...")
        self.eleven_status.grid(row=0, column=3, sticky="w", padx=4)

        self.eleven_mcp_frame = ttk.Frame(f)
        self.eleven_mcp_frame.grid(row=r, column=0, columnspan=4, sticky="w", padx=10)
        ttk.Label(
            self.eleven_mcp_frame,
            text="ElevenLabs도 Claude Code에서 /mcp 로 직접 연결하면 API 키 없이 쓸 수 있습니다.\n"
                 "이 화면은 그 연결을 대신 해줄 수 없습니다 -- 연결되어 있으면 파이프라인이 자동으로 그쪽을 씁니다.",
            foreground="#555",
            justify="left",
        ).grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.eleven_mcp_frame.grid_remove()
        r += 1

        ttk.Separator(f).grid(row=r, column=0, columnspan=4, sticky="ew", padx=10, pady=4)
        r += 1

        ttk.Label(f, text="영상 생성 서비스", font=("", 10, "bold")).grid(row=r, column=0, sticky="w", **pad)
        self.provider_var = tk.StringVar(value="higgsfield_api")
        ttk.Radiobutton(f, text="Higgsfield (API 키)", variable=self.provider_var, value="higgsfield_api",
                        command=self._toggle_provider).grid(row=r, column=1, sticky="w", **pad)
        ttk.Radiobutton(f, text="Higgsfield (MCP)", variable=self.provider_var, value="higgsfield_mcp",
                        command=self._toggle_provider).grid(row=r, column=2, sticky="w", **pad)
        ttk.Radiobutton(f, text="OpenArt (Claude Code MCP)", variable=self.provider_var, value="openart",
                        command=self._toggle_provider).grid(row=r, column=3, sticky="w", **pad)
        r += 1

        self.higgs_frame = ttk.Frame(f)
        self.higgs_frame.grid(row=r, column=0, columnspan=4, sticky="w", padx=10)
        ttk.Label(self.higgs_frame, text="KEY_ID").grid(row=0, column=0, sticky="w", padx=4)
        self.higgs_id_var = tk.StringVar()
        ttk.Entry(self.higgs_frame, textvariable=self.higgs_id_var, width=24).grid(row=0, column=1, padx=4)
        ttk.Label(self.higgs_frame, text="KEY_SECRET").grid(row=0, column=2, sticky="w", padx=4)
        self.higgs_secret_var = tk.StringVar()
        ttk.Entry(self.higgs_frame, textvariable=self.higgs_secret_var, show="*", width=24).grid(row=0, column=3, padx=4)
        ttk.Button(self.higgs_frame, text="저장", command=self._save_higgsfield).grid(row=0, column=4, padx=6)

        self.higgs_mcp_frame = ttk.Frame(f)
        self.higgs_mcp_frame.grid(row=r, column=0, columnspan=4, sticky="w", padx=10)
        ttk.Label(
            self.higgs_mcp_frame,
            text="Higgsfield의 공식 호스팅 MCP(mcp.higgsfield.ai)를 claude CLI에 등록합니다 (API 키 불필요, 유료 구독 계정 필요).\n"
                 "등록 후 다음에 claude를 쓸 때 브라우저 로그인(OAuth)이 한 번 더 필요합니다.",
            foreground="#555",
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=4, pady=4)
        self.higgs_mcp_status = ttk.Label(self.higgs_mcp_frame, text="확인 중...")
        self.higgs_mcp_status.grid(row=1, column=0, sticky="w", padx=4)
        ttk.Button(self.higgs_mcp_frame, text="등록", command=self._connect_higgsfield_mcp).grid(row=1, column=1, padx=6)
        self.higgs_mcp_frame.grid_remove()

        self.openart_frame = ttk.Frame(f)
        self.openart_frame.grid(row=r, column=0, columnspan=4, sticky="w", padx=10)
        ttk.Label(
            self.openart_frame,
            text="OpenArt는 API 키가 없습니다 -- Claude Code에서 /mcp 로 OpenArt 계정을 직접 연결해주세요.\n"
                 "이 화면은 그 연결을 대신 해줄 수 없습니다.",
            foreground="#555",
            justify="left",
        ).grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.openart_frame.grid_remove()
        r += 1

        ttk.Separator(f).grid(row=r, column=0, columnspan=4, sticky="ew", padx=10, pady=8)
        r += 1

        ttk.Label(f, text="YouTube 연결", font=("", 10, "bold")).grid(row=r, column=0, sticky="w", **pad)
        self.youtube_status = ttk.Label(f, text="확인 중...")
        self.youtube_status.grid(row=r, column=1, columnspan=2, sticky="w", **pad)
        ttk.Button(f, text="로그인 (브라우저 열림)", command=self._youtube_auth).grid(row=r, column=3, **pad)
        r += 1

        ttk.Label(
            f,
            text="처음이라면 Google Cloud Console에서 OAuth 클라이언트(Desktop app)를 만들고\n"
                 "client_secret_*.json을 받아야 합니다 (docs/youtube-upload.md 참고).",
            foreground="#555",
            justify="left",
        ).grid(row=r, column=0, columnspan=4, sticky="w", padx=10, pady=2)
        r += 1
        ttk.Button(f, text="client_secret.json 선택...", command=self._pick_client_secret).grid(
            row=r, column=0, sticky="w", padx=10, pady=4
        )
        self.client_secret_label = ttk.Label(f, text=get_env_var("YOUTUBE_CLIENT_SECRETS_FILE") or "(미설정)")
        self.client_secret_label.grid(row=r, column=1, columnspan=3, sticky="w", padx=10)
        r += 1

        ttk.Separator(f).grid(row=r, column=0, columnspan=4, sticky="ew", padx=10, pady=8)
        r += 1

        ttk.Label(f, text="필수 프로그램 (uv / ffmpeg / Node.js / Claude CLI)", font=("", 10, "bold")).grid(
            row=r, column=0, columnspan=2, sticky="w", **pad
        )
        self.claude_cli_status = ttk.Label(f, text="확인 중...")
        self.claude_cli_status.grid(row=r, column=2, sticky="w", **pad)
        ttk.Button(f, text="설치", command=self._install_claude_cli).grid(row=r, column=3, **pad)
        r += 1
        ttk.Label(
            f,
            text="실행 탭이 실제로 영상을 만드는 데 전부 필요합니다. 이 PC에 없는 것만 자동으로 설치합니다.",
            foreground="#555",
            justify="left",
        ).grid(row=r, column=0, columnspan=4, sticky="w", padx=10)
        r += 1

        ttk.Label(f, text="Claude 로그인", font=("", 10, "bold")).grid(row=r, column=0, sticky="w", **pad)
        self.claude_login_status = ttk.Label(f, text="확인 중...")
        self.claude_login_status.grid(row=r, column=1, columnspan=2, sticky="w", **pad)
        ttk.Button(f, text="로그인 (브라우저 열림)", command=self._login_claude).grid(row=r, column=3, **pad)
        r += 1
        ttk.Label(
            f,
            text="방금 설치한 claude CLI는 이 PC의 다른 Claude 로그인과 별개로, 한 번 더 로그인해야 합니다.",
            foreground="#555",
            justify="left",
        ).grid(row=r, column=0, columnspan=4, sticky="w", padx=10)
        r += 1

        self.install_log = tk.Text(f, height=8, wrap="word", state="disabled")
        self.install_log.grid(row=r, column=0, columnspan=4, sticky="nsew", padx=10, pady=(6, 10))

        f.columnconfigure(3, weight=1)
        f.rowconfigure(r, weight=1)

    def _toggle_eleven_mode(self) -> None:
        if self.eleven_mode_var.get() == "api":
            self.eleven_mcp_frame.grid_remove()
            self.eleven_api_frame.grid()
        else:
            self.eleven_api_frame.grid_remove()
            self.eleven_mcp_frame.grid()

    def _toggle_provider(self) -> None:
        choice = self.provider_var.get()
        self.higgs_frame.grid_remove()
        self.higgs_mcp_frame.grid_remove()
        self.openart_frame.grid_remove()
        if choice == "higgsfield_api":
            self.higgs_frame.grid()
        elif choice == "higgsfield_mcp":
            self.higgs_mcp_frame.grid()
        else:
            self.openart_frame.grid()

    def _save_eleven_key(self) -> None:
        key = self.eleven_key_var.get().strip()
        if not key:
            return
        set_env_var("ELEVENLABS_API_KEY", key)
        self.eleven_key_var.set("")
        messagebox.showinfo("저장됨", "ElevenLabs 키를 저장했습니다.")
        self._refresh_status()

    def _save_higgsfield(self) -> None:
        key_id = self.higgs_id_var.get().strip()
        secret = self.higgs_secret_var.get().strip()
        if not (key_id and secret):
            messagebox.showwarning("입력 필요", "KEY_ID와 KEY_SECRET을 모두 입력해주세요.")
            return
        set_env_var("HIGGSFIELD_KEY_ID", key_id)
        set_env_var("HIGGSFIELD_KEY_SECRET", secret)
        messagebox.showinfo("저장됨", "Higgsfield 키를 저장했습니다.")

    def _pick_client_secret(self) -> None:
        path = filedialog.askopenfilename(title="client_secret json 선택", filetypes=[("JSON", "*.json")])
        if path:
            set_env_var("YOUTUBE_CLIENT_SECRETS_FILE", path)
            self.client_secret_label.config(text=path)

    def _youtube_auth(self) -> None:
        self._run_in_background(self._do_youtube_auth, "유튜브 로그인 중... 브라우저 창을 확인하세요.")

    def _do_youtube_auth(self) -> None:
        import subprocess

        from shorts_common import ROOT
        from win_encoding import utf8_env

        subprocess.run(
            ["uv", "run", "--extra", "youtube", "tools/youtube_upload.py", "--auth", "--account", "default"],
            cwd=ROOT,
            env=utf8_env(),
        )
        self.after(0, self._refresh_status)

    def _refresh_status(self) -> None:
        self.eleven_status.config(text="OK" if get_env_var("ELEVENLABS_API_KEY") else "미설정")
        self.higgs_mcp_status.config(text="등록됨" if check_higgsfield_mcp() else "미등록")
        data = check_youtube()
        ch = (data or {}).get("channel")
        self.youtube_status.config(text=f"연결됨: {ch['title']}" if ch else "미연결")
        status = check_toolchain_status()
        core = {k: v for k, v in status.items() if k != "claude-login"}
        if all(core.values()):
            self.claude_cli_status.config(text="전부 설치됨")
        else:
            missing = [name for name, ok in core.items() if not ok]
            self.claude_cli_status.config(text=f"누락: {', '.join(missing)}")
        self.claude_login_status.config(text="로그인됨" if status.get("claude-login") else "미로그인")

    def _log_install(self, line: str) -> None:
        self._install_log_queue.put(line)

    def _drain_install_log_queue(self) -> None:
        try:
            while True:
                line = self._install_log_queue.get_nowait()
                self.install_log.config(state="normal")
                self.install_log.insert("end", line + "\n")
                self.install_log.see("end")
                self.install_log.config(state="disabled")
        except queue.Empty:
            pass
        self.after(150, self._drain_install_log_queue)

    def _install_claude_cli(self) -> None:
        if self._installing_claude:
            messagebox.showwarning("진행 중", "이미 설치가 진행 중입니다.")
            return
        self._installing_claude = True
        self._log_install("=== 필수 프로그램 설치 시작 (이 창을 닫지 마세요) ===")

        def worker() -> None:
            try:
                ensure_full_toolchain(on_line=self._log_install)
            finally:
                self._installing_claude = False
                self.after(0, self._refresh_status)

        threading.Thread(target=worker, daemon=True).start()

    def _login_claude(self) -> None:
        if self._installing_claude:
            messagebox.showwarning("진행 중", "다른 설치/로그인 작업이 진행 중입니다.")
            return
        self._installing_claude = True
        self._log_install("=== Claude 로그인 시작 -- 브라우저에서 로그인을 완료해주세요 ===")

        def worker() -> None:
            try:
                login_claude_cli(on_line=self._log_install)
            finally:
                self._installing_claude = False
                self.after(0, self._refresh_status)

        threading.Thread(target=worker, daemon=True).start()

    def _connect_higgsfield_mcp(self) -> None:
        if self._installing_claude:
            messagebox.showwarning("진행 중", "다른 설치/로그인 작업이 진행 중입니다.")
            return
        self._installing_claude = True
        self._log_install("=== Higgsfield MCP 등록 시작 ===")

        def worker() -> None:
            try:
                connect_higgsfield_mcp(on_line=self._log_install)
            finally:
                self._installing_claude = False
                self.after(0, self._refresh_status)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # 실행 탭
    # ------------------------------------------------------------------

    def _build_run_tab(self) -> None:
        f = self.run_tab
        pad = {"padx": 10, "pady": 6}

        ttk.Label(f, text="주제").grid(row=0, column=0, sticky="w", **pad)
        self.topic_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.topic_var, width=50).grid(row=0, column=1, columnspan=3, sticky="we", **pad)

        ttk.Label(f, text="영상 길이 (초, 최대 60)").grid(row=1, column=0, sticky="w", **pad)
        self.duration_var = tk.IntVar(value=30)
        ttk.Spinbox(f, from_=5, to=60, textvariable=self.duration_var, width=8).grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(f, text="영상 개수").grid(row=1, column=2, sticky="e", **pad)
        self.count_var = tk.IntVar(value=1)
        ttk.Spinbox(f, from_=1, to=20, textvariable=self.count_var, width=8).grid(row=1, column=3, sticky="w", **pad)

        self.upload_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="완성 후 유튜브에 업로드", variable=self.upload_var).grid(
            row=2, column=0, columnspan=2, sticky="w", **pad
        )

        ttk.Label(f, text="저장 위치").grid(row=3, column=0, sticky="w", **pad)
        self.output_dir_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.output_dir_var, width=42).grid(row=3, column=1, columnspan=2, sticky="we", **pad)
        ttk.Button(f, text="폴더 선택...", command=self._pick_output_dir).grid(row=3, column=3, sticky="w", **pad)
        ttk.Label(
            f, text="(비워두면 shorts-jobs/<주제>/output/ 에만 남깁니다)", foreground="#555"
        ).grid(row=4, column=1, columnspan=3, sticky="w", padx=10)

        self.start_button = ttk.Button(f, text="시작", command=self._start_run)
        self.start_button.grid(row=5, column=0, sticky="w", **pad)
        self.cancel_button = ttk.Button(f, text="취소", command=self._cancel_run, state="disabled")
        self.cancel_button.grid(row=5, column=1, sticky="w", **pad)
        self.open_output_button = ttk.Button(f, text="저장 위치 열기", command=self._open_output_dir, state="disabled")
        self.open_output_button.grid(row=5, column=3, sticky="e", **pad)

        self.log_text = tk.Text(f, height=20, wrap="word", state="disabled")
        self.log_text.grid(row=6, column=0, columnspan=4, sticky="nsew", padx=10, pady=(4, 10))

        f.columnconfigure(1, weight=1)
        f.rowconfigure(6, weight=1)

    def _pick_output_dir(self) -> None:
        path = filedialog.askdirectory(title="완성된 mp4를 저장할 폴더 선택")
        if path:
            self.output_dir_var.set(path)

    def _open_output_dir(self) -> None:
        path = self.output_dir_var.get().strip()
        if path and Path(path).is_dir():
            import os

            os.startfile(path)  # noqa: S606 -- Windows only, user's own chosen folder

    def _log(self, line: str) -> None:
        self._log_queue.put(line)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                line = self._log_queue.get_nowait()
                self.log_text.config(state="normal")
                self.log_text.insert("end", line + "\n")
                self.log_text.see("end")
                self.log_text.config(state="disabled")
        except queue.Empty:
            pass
        self.after(150, self._drain_log_queue)

    def _run_in_background(self, target, start_message: str) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showwarning("진행 중", "이미 다른 작업이 실행 중입니다.")
            return
        self._log(start_message)
        self._worker = threading.Thread(target=target, daemon=True)
        self._worker.start()

    def _start_run(self) -> None:
        topic = self.topic_var.get().strip()
        if not topic:
            messagebox.showwarning("주제 필요", "주제를 입력해주세요.")
            return
        if not shutil.which("claude"):
            messagebox.showerror(
                "claude CLI 없음",
                "'claude' CLI를 찾을 수 없습니다. '설치' 탭에서 필수 프로그램 설치 버튼을 눌러주세요.",
            )
            return
        if not check_claude_auth():
            messagebox.showerror(
                "로그인 필요",
                "claude CLI가 로그인되어 있지 않습니다. '설치' 탭의 'Claude 로그인' 버튼을 먼저 눌러주세요.",
            )
            return

        duration = int(self.duration_var.get())
        count = int(self.count_var.get())
        upload = bool(self.upload_var.get())
        output_dir_raw = self.output_dir_var.get().strip()
        output_dir = Path(output_dir_raw) if output_dir_raw else None

        if upload:
            data = check_youtube()
            ch = (data or {}).get("channel")
            if not ch:
                if not messagebox.askyesno(
                    "유튜브 미연결",
                    "연결된 유튜브 채널이 없습니다. 업로드 없이 영상만 만들까요?",
                ):
                    return
                upload = False
                channel_label = None
            else:
                channel_label = f"{ch['title']} ({ch['id']})"
                if not messagebox.askyesno("채널 확인", f"'{channel_label}' 채널에 업로드하는 게 맞습니까?"):
                    return
        else:
            channel_label = None

        self._cancel_requested = False
        self.start_button.config(state="disabled")
        self.cancel_button.config(state="normal")
        self._run_in_background(
            lambda: self._do_run(topic, duration, count, upload, channel_label, output_dir),
            f"=== 시작: {topic} / {duration}s / {count}개 / 업로드={'예' if upload else '아니오'} ===",
        )

    def _cancel_run(self) -> None:
        self._cancel_requested = True
        self._log("취소를 요청했습니다 -- 현재 진행 중인 영상은 끝까지 진행되고 다음 영상부터 멈춥니다.")

    def _do_run(
        self,
        topic: str,
        duration: int,
        count: int,
        upload: bool,
        channel_label: str | None,
        output_dir: Path | None,
    ) -> None:
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)

        slug = slugify(topic)
        for i in range(1, count + 1):
            if self._cancel_requested:
                self._log(f"[{i}/{count}] 취소됨 -- 중단합니다.")
                break

            job_id = new_job_id(slug, i, count)
            self._log(f"\n[{i}/{count}] shorts-jobs/{job_id} 작업을 시작합니다...")
            prompt_text = build_pipeline_prompt(job_id, topic, duration, upload, channel_label)
            run_started_at = time.time()
            rc = run_claude_headless(prompt_text, on_line=self._log)

            if rc != 0:
                self._log(f"  [{i}/{count}] claude 세션이 비정상 종료됐습니다 (exit {rc}) -- shorts-jobs/{job_id} 폴더를 확인하세요.")
                continue

            # claude -p가 exit 0으로 끝났다고 해서 작업이 실제로 성공했다는 뜻은 아니다 (막혀서
            # 보고만 하고 끝난 세션도 exit 0이다) -- 진짜 결과물이 있는지로 성공 여부를 판단한다.
            src = find_final_mp4(job_id, run_started_at)
            if src is None:
                self._log(f"  [{i}/{count}] 세션은 끝났지만 영상을 만들지 못한 것 같습니다 -- shorts-jobs/{job_id} 폴더를 확인하세요.")
                continue

            actual_job = src.parent.parent.name
            if actual_job != job_id:
                match = verify_job_topic(src.parent.parent, topic)
                if match is False:
                    self._log(
                        f"  [{i}/{count}] 'shorts-jobs/{actual_job}'에서 영상을 찾았지만 주제가 요청하신 "
                        f"'{topic}'와 달라서 이번 요청 결과로 보지 않습니다 -- 이번 요청은 사실상 실패입니다. "
                        f"shorts-jobs/{job_id} 폴더를 직접 확인하세요."
                    )
                    continue
                self._log(f"  참고: 에이전트가 지시한 폴더 대신 'shorts-jobs/{actual_job}'에 결과를 만들었습니다.")

            self._log(f"  [{i}/{count}] 완료 -- {src}")
            if output_dir is not None:
                dest = output_dir / f"{job_id}.mp4"
                dest.write_bytes(src.read_bytes())
                self._log(f"  -> {dest} 로 복사했습니다.")

        self._log("\n=== 전체 작업 종료 ===")
        self.after(0, lambda: self.start_button.config(state="normal"))
        self.after(0, lambda: self.cancel_button.config(state="disabled"))
        if output_dir is not None:
            self.after(0, lambda: self.open_output_button.config(state="normal"))


def main() -> int:
    ensure_utf8_output()
    refresh_path_from_registry()
    app = ShortsMakerApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
