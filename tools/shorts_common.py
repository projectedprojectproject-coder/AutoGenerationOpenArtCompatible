"""Shared helpers for the Shorts CLI and GUI (tools/shorts_cli.py, tools/shorts_gui.py).

Kept dependency-free (stdlib only, plus win_encoding) so it can be frozen by PyInstaller
without dragging in elevenlabs/numpy/etc. -- those only ever run inside a separate
`uv run tools/<tool>.py` subprocess using the project's own managed venv.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from win_encoding import utf8_env  # noqa: E402


def project_root() -> Path:
    """The toolkit root, whether running as a plain script or a frozen PyInstaller exe.

    A frozen exe is expected to live at the toolkit root (same convention as the
    .bat launchers: `cd /d "%~dp0"`), so its own directory IS the root.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT = project_root()
ENV_PATH = ROOT / ".env"
JOBS_DIR = ROOT / "shorts-jobs"


def refresh_path_from_registry() -> None:
    """Merge the persisted Machine+User PATH into this process's PATH.

    A process launched from an Explorer window (or any shell) that was already open
    before an installer modified PATH inherits the *stale* copy -- this is the same
    fix applied to install-shorts.bat/make-short.bat, done here in pure Python so the
    frozen .exe needs no wrapper script at all. Windows-only; a no-op elsewhere.
    """
    if os.name != "nt":
        return
    try:
        import winreg

        def read(hive, subkey) -> str:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
                return os.path.expandvars(value)

        machine = read(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")
        try:
            user = read(winreg.HKEY_CURRENT_USER, "Environment")
        except FileNotFoundError:
            user = ""
        merged = ";".join(p for p in (machine, user, os.environ.get("PATH", "")) if p)
        os.environ["PATH"] = merged
    except Exception:
        # Never let a PATH refresh failure block the app -- worst case, the
        # in-memory PATH this process already has is used as-is.
        pass


def read_env_lines() -> list[str]:
    if ENV_PATH.exists():
        return ENV_PATH.read_text(encoding="utf-8").splitlines()
    return []


def set_env_var(key: str, value: str) -> None:
    """Set KEY=value in .env: replace a live or commented-placeholder line, else append."""
    lines = read_env_lines()
    live = re.compile(rf"^\s*{re.escape(key)}\s*=")
    commented = re.compile(rf"^\s*#\s*{re.escape(key)}\s*=")
    for i, line in enumerate(lines):
        if live.match(line):
            lines[i] = f"{key}={value}"
            ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    for i, line in enumerate(lines):
        if commented.match(line):
            lines[i] = f"{key}={value}"
            ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def get_env_var(key: str) -> str | None:
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH)
    return os.environ.get(key)


def run_uv(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["uv", "run", *args], cwd=ROOT, env=utf8_env(), encoding="utf-8", **kw)


def check_youtube(account: str = "default") -> dict | None:
    r = run_uv(
        ["--extra", "youtube", "tools/youtube_upload.py", "--check", "--account", account, "--json-out"],
        capture_output=True,
    )
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def slugify(text: str, max_len: int = 30) -> str:
    # NFC, not NFKD: NFKD *decomposes* precomposed characters -- for Hangul that means every
    # syllable block splits into its separate jamo (the "다 풀어지는" symptom this fixes). NFC
    # keeps/returns composed form, which \w already matches fine, so nothing needs decomposing
    # here in the first place.
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    return (text or "short")[:max_len].strip("-") or "short"


def new_job_id(slug: str, index: int, count: int) -> str:
    base_id = f"{slug}-{index:02d}" if count > 1 else slug
    job_id = base_id
    n = 1
    while (JOBS_DIR / job_id).exists():
        n += 1
        job_id = f"{base_id}-{n}"
    return job_id


_FREE_TOPIC_PLACEHOLDERS = {"anything", "자유", "자유주제", "아무거나", "아무 주제", "", "free", "random"}


def is_free_topic(topic: str) -> bool:
    return topic.strip().lower() in _FREE_TOPIC_PLACEHOLDERS


def build_pipeline_prompt(job_id: str, topic: str, duration: int, upload: bool, channel_label: str | None) -> str:
    upload_note = (
        f"완성되면 '{channel_label}' 채널에 업로드까지 진행해라 -- 이 실행은 사람이 중간에 응답할 수 없는 무인 배치이므로, "
        "Publisher가 approved 판정을 내리고 계정을 조회한 뒤에는 추가 확인 질문 없이 바로 업로드를 실행해라 "
        "(사용자가 이 배치 전체에 대해 이미 승인했다)."
        if upload
        else "업로드는 하지 마라 -- 최종 mp4를 만드는 것까지만 진행해라."
    )
    topic_instruction = (
        f'"{topic}"는 자유 주제 요청이다. `.claude/agents/topic-picker.md`를 Read로 읽고, 그 기준에 따라 '
        "**네가 직접**(Agent 도구로 아무도 호출하지 말고) 구체적인 주제를 정해서 topic.json에 써라."
        if is_free_topic(topic)
        else (
            f'주제는 정확히 "{topic}"이다. **네가 직접**(Agent 도구로 아무도 호출하지 말고) 이 문자열을 '
            "**토씨 하나 바꾸지 않고 그대로** topic.json의 topic 필드에 써라. 요약하거나, 순화하거나, 더 "
            "낫다고 판단되는 다른 주제로 바꾸지 않는다."
        )
    )
    return (
        "shorts-pipeline 스킬을 따라 숏츠를 자동으로 제작해라.\n"
        "\n"
        "**아래 규칙들을 가장 먼저, 가장 중요하게 지켜라 -- 과거에 전부 실제로 깨진 적이 있다:**\n"
        "\n"
        f"1. **작업 폴더는 정확히 `shorts-jobs/{job_id}` 하나뿐이다.** 모든 단계가 이 폴더만 쓴다. 비슷한 "
        "이름의 새 폴더를 만들거나, `shorts-jobs/` 아래 이미 있는 다른 작업 폴더(타임스탬프 이름 등)를 대신 "
        f"골라 이어가지 마라. 이 실행을 띄운 프로그램은 정확히 `shorts-jobs/{job_id}/output/final_v*.mp4`에서만 "
        "결과물을 찾는다 -- 다른 폴더에 만들면 그 프로그램은 완성된 영상을 영영 찾지 못한다.\n"
        f"2. **topic.json은 네가(오케스트레이터) 직접 쓴다 -- Agent 도구로 topic-picker나 다른 누구도 부르지 "
        f"마라.** {topic_instruction} 서브에이전트를 거치면 호출 프롬프트에 주제를 옮겨 적는 과정에서 주제가 "
        "누락되고, 그러면 받는 쪽이 자유 주제 요청으로 오해해서 완전히 다른 주제를 멋대로 고르는 사고가 "
        "**세 번 연속** 일어났다 -- 그래서 이 단계는 서브에이전트 호출 자체를 없앴다. 네가 직접 쓰면 이 문제가 "
        "생길 수 없다. 주제 자체를 정말 다룰 수 없다고 판단되면(드물어야 한다) topic.json을 쓰지 말고 멈춰서 "
        "이유를 명확히 보고해라 -- 절대 다른 주제로 조용히 바꾸지 마라.\n"
        "\n"
        f"- target_duration_s: {duration}, tone: 흥미/정보, language: ko, aspect_ratio: 9:16\n"
        f"- topic.json을 쓴 뒤, scalper/script-qa-looper/title-picker/title-qa-looper/spawner/tts-spawner/"
        "qa-tts-looper/qa-looper/editor/subtitles/subtitles-qa-looper/publisher를 순서대로 호출해서 끝까지 "
        "자동으로 진행해라. title-picker/title-qa-looper는 영상 상단에 번인할 짧은 타이틀 문구를 정하고 "
        "검수하는 단계로, script-qa-looper 통과 직후(spawner 전)에 끼워 넣는다 -- editor가 나중에 그 문구를 "
        "그대로 화면 상단에 번인한다.\n"
        "\n"
        "**영상 소스 생성(OpenArt MCP 경로)은 spawner 서브에이전트에 위임하지 마라.** 서브에이전트는 OpenArt MCP "
        "도구 자체에 접근하지 못하는 것으로 확인됐다 (권한이 아니라 연결이 안 됨). 대신 네가(지금 이 세션, "
        "오케스트레이터) `.claude/agents/spawner.md`를 Read로 읽고, 그 안의 'OpenArt MCP 호출 흐름' 절차를 "
        "**네가 직접** 수행해서(사용 가능한 도구 중 openart_generate_video/openart_creation_get 등으로 끝나는 "
        "이름을 찾아 호출) `shorts-jobs/<id>/assets/`를 채워라. Higgsfield 폴백이나 그 외 나머지 작업(재생성 "
        "모드, 완료 보고 등)은 spawner.md에 적힌 대로 spawner 서브에이전트에게 맡겨도 된다 -- MCP 호출 부분만 "
        "예외다.\n"
        "\n"
        "**음성(TTS)도 마찬가지 원칙이다**: `.env`에 `ELEVENLABS_API_KEY`가 있으면 tts-spawner 서브에이전트가 "
        "`tools/voiceover.py`로 그대로 처리한다(Bash라서 서브에이전트도 쓸 수 있다). 키가 없고 대신 ElevenLabs "
        "MCP 도구(이름이 text_to_speech 등으로 끝나는 도구)가 보이면, 그때는 OpenArt와 같은 이유로 **네가 "
        "직접** 그 도구를 호출해서 `shorts-jobs/<id>/audio/`를 채워라 -- tts-spawner에게 MCP 호출을 시키지 마라.\n"
        "\n"
        "**이건 사람이 중간에 답할 수 없는 무인 배치 실행이다. 다음 행동은 절대 하지 마라:**\n"
        '- "주제를 알려주세요", "~해도 될까요?", "다음 중 선택해주세요" 같은 질문을 출력하고 멈추는 것\n'
        "- 판단이 필요한 지점(씬 구성, 보이스, 트림 구간, 모델 선택 등)에서 사용자 확인을 기다리는 것\n"
        "- 확신이 없다는 이유로 topic.json/research.json 등 필요한 파일 작성을 보류하는 것\n"
        "\n"
        "대신: 애매한 판단은 각 에이전트 정의에 적힌 기본값과 루프 규칙대로 네가 직접 결정해서 진행하고, "
        "그 결정 이유는 최종 요약에 한 줄로만 남겨라. 정말로 더 진행할 수 없는 경우(루프 한도 초과, 자격증명 "
        "누락 등)에만 상태를 기록하고 세션을 종료해라 -- 그것도 질문이 아니라 보고로 끝내라.\n"
        f"- {upload_note}\n"
        "완료되면 최종 결과(mp4 경로, 통과 루프 수, 업로드 여부)를 한 문단으로 요약해라."
    )


def latest_final_mp4(job_id: str) -> Path | None:
    """The highest-numbered output/final_v*.mp4 for a job, or None if there isn't one yet."""
    out_dir = JOBS_DIR / job_id / "output"
    if not out_dir.is_dir():
        return None
    candidates = sorted(
        out_dir.glob("final_v*.mp4"),
        key=lambda p: int(m.group(1)) if (m := re.search(r"final_v(\d+)\.mp4$", p.name)) else -1,
    )
    return candidates[-1] if candidates else None


def find_final_mp4(job_id: str, run_started_at: float | None = None) -> Path | None:
    """`latest_final_mp4(job_id)`, falling back to the newest `final_v*.mp4` anywhere under
    `shorts-jobs/` if the expected job folder has none.

    The headless agent is told to use exactly `shorts-jobs/<job_id>`, but nothing stops it from
    resuming a different, already-in-progress job folder it finds instead. `run_started_at` (a
    `time.time()` taken right before the run), when given, restricts the fallback to files
    modified at or after that moment -- strictly *after* this run started, never before, so a
    failed run can't silently hand back some unrelated older job's leftover video. A 2-second
    tolerance only covers clock-precision slop between this process and the child's, not "maybe
    it was already sitting there."

    Caller should still check `verify_job_topic()` on whatever this returns when the fallback
    path (a different folder than `job_id`) was taken -- "newest file" is not "the right file."
    """
    exact = latest_final_mp4(job_id)
    if exact is not None:
        return exact
    if not JOBS_DIR.is_dir():
        return None
    candidates = list(JOBS_DIR.glob("*/output/final_v*.mp4"))
    if run_started_at is not None:
        candidates = [p for p in candidates if p.stat().st_mtime >= run_started_at - 2]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def verify_job_topic(job_dir: Path, requested_topic: str) -> bool | None:
    """Does `job_dir/topic.json`'s recorded topic match what was actually requested?

    Returns True/False when it can tell, or None when it can't (missing file, or the request was
    a free-topic placeholder that topic-picker was always going to replace with something else).
    Meant to guard the `find_final_mp4` fallback: finding *a* recent video is not the same as
    finding *this run's* video, and copying the wrong one into the user's chosen output file under
    the name they expect is worse than reporting nothing.
    """
    if is_free_topic(requested_topic):
        return None
    topic_path = job_dir / "topic.json"
    if not topic_path.is_file():
        return None
    try:
        recorded = json.loads(topic_path.read_text(encoding="utf-8")).get("topic", "")
    except Exception:
        return None
    norm = lambda s: re.sub(r"\s+", "", str(s)).strip("?.!")
    return norm(recorded) == norm(requested_topic)


def _resolve_shim_target(shim_path: str) -> list[str] | None:
    """Look inside an npm-generated .cmd/.bat shim for the real program it hands off to.

    npm shims come in two shapes: a thin wrapper around a bundled native .exe (e.g. this
    toolkit's `claude.cmd`, which just runs `"%dp0%\\...\\claude.exe" %*`), or a `node "<script.js>"
    %*` wrapper around a JS entry point (classic npm CLI shims, e.g. older `npm.cmd` style).
    Either way, invoking the thing it hands off to *directly* -- skipping `.cmd`/`.bat` and the
    cmd.exe layer that has to run it -- avoids cmd.exe's own command-line re-tokenization.

    That re-tokenization is not a cosmetic issue: a long, multi-line argument full of embedded
    `"` (exactly what a pipeline prompt looks like) gets silently corrupted and truncated when
    routed through `cmd /c`, with no error -- confirmed by direct test. Every later argument can
    end up dropped or merged into the one before it. Returns `[argv0, ...]` for the resolved real
    program (no later args attached yet), or None if no such hand-off could be found.
    """
    try:
        text = Path(shim_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    shim_dir = str(Path(shim_path).resolve().parent)

    def expand(p: str) -> str:
        return p.replace("%dp0%", shim_dir + "\\").replace("%~dp0%", shim_dir + "\\").replace("%~dp0", shim_dir)

    m = re.search(r'"([^"]+\.exe)"', text, re.IGNORECASE)
    if m:
        exe = expand(m.group(1))
        if Path(exe).is_file():
            return [exe]

    m = re.search(r'\bnode\s+"([^"]+\.(?:js|cjs|mjs))"', text, re.IGNORECASE)
    if m:
        script = expand(m.group(1))
        node = shutil.which("node")
        if node and Path(script).is_file():
            return [node, script]

    return None


def _windows_safe_argv(cmd: list[str]) -> list[str]:
    """Make an argv list actually launchable by `subprocess.Popen(..., shell=False)` on Windows.

    CreateProcess (what Popen uses under shell=False) cannot execute a .cmd/.bat file directly --
    only cmd.exe can. `npm`, `claude` and friends are installed as .cmd shims on Windows, so a plain
    `Popen(["npm", "install", ...])` raises `FileNotFoundError: [WinError 2]` even though `npm` is
    right there on PATH and `shutil.which("npm")` finds it.

    Resolve the real path first. If it's a .cmd/.bat, prefer unwrapping it to the real program it
    hands off to (see `_resolve_shim_target`) -- this is not just an optimization, it is the fix
    for a real data-corruption bug: routing a long, quote-and-newline-heavy argument (a pipeline
    prompt) through `cmd /c` silently truncates/drops it and later arguments, with no error. Only
    fall back to `cmd /c` (still as a list, so normal argv quoting applies) when no underlying
    program can be found. No-op on non-Windows or for a path that is already a real .exe.
    """
    if os.name != "nt" or not cmd:
        return cmd
    resolved = shutil.which(cmd[0])
    if not resolved:
        return cmd
    if resolved.lower().endswith((".cmd", ".bat")):
        target = _resolve_shim_target(resolved)
        if target:
            return [*target, *cmd[1:]]
        return ["cmd", "/c", resolved, *cmd[1:]]
    return [resolved, *cmd[1:]]


def _stream_subprocess(cmd: list[str], on_line=None) -> int:
    try:
        proc = subprocess.Popen(
            _windows_safe_argv(cmd),
            cwd=ROOT,
            env=utf8_env(),
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
    except OSError as exc:
        if on_line:
            on_line(f"실행 실패: {' '.join(cmd)} ({exc})")
        return -1
    assert proc.stdout is not None
    for line in proc.stdout:
        if on_line:
            on_line(line.rstrip("\n"))
    proc.wait()
    return proc.returncode


def check_claude_cli() -> str | None:
    return shutil.which("claude")


def ensure_claude_cli(on_line=None) -> bool:
    """Best-effort: install Node.js (winget) and the claude CLI (npm) on *this* machine if missing.

    Must run on the machine the GUI/exe is actually launched on -- a `claude` CLI installed from
    wherever a development session's own shell tool happened to run does NOT show up here; it has
    to be installed by code executing in this very process. Returns True if `claude` resolves on
    PATH by the end (already present, or freshly installed).
    """
    refresh_path_from_registry()
    if shutil.which("claude"):
        if on_line:
            on_line("claude CLI: 이미 설치되어 있습니다.")
        return True

    if not shutil.which("node"):
        if not shutil.which("winget"):
            if on_line:
                on_line("winget을 찾을 수 없습니다. Microsoft Store에서 'App Installer'를 설치하거나,")
                on_line("https://nodejs.org 에서 Node.js를 직접 설치한 뒤 다시 시도해주세요.")
            return False
        if on_line:
            on_line("Node.js가 없어서 먼저 설치합니다 (winget)...")
        rc = _stream_subprocess(
            [
                "winget", "install", "--id", "OpenJS.NodeJS.LTS", "-e",
                "--accept-source-agreements", "--accept-package-agreements",
            ],
            on_line,
        )
        refresh_path_from_registry()
        if rc != 0 or not shutil.which("node"):
            if on_line:
                on_line(f"Node.js 설치에 실패했습니다 (exit {rc}). 수동으로 설치한 뒤 다시 시도해주세요.")
            return False
        if on_line:
            on_line("Node.js 설치 완료.")

    if on_line:
        on_line("claude CLI를 설치합니다 (npm install -g @anthropic-ai/claude-code)...")
    rc = _stream_subprocess(["npm", "install", "-g", "@anthropic-ai/claude-code"], on_line)
    refresh_path_from_registry()
    ok = shutil.which("claude") is not None
    if on_line:
        on_line("claude CLI 설치 완료." if ok else f"claude CLI 설치에 실패했습니다 (exit {rc}).")
    return ok


def _ensure_via_winget(name: str, winget_id: str, on_line=None) -> bool:
    refresh_path_from_registry()
    if shutil.which(name):
        return True
    if not shutil.which("winget"):
        if on_line:
            on_line(f"winget이 없어 {name}를 자동 설치할 수 없습니다. 직접 설치한 뒤 다시 시도해주세요.")
        return False
    if on_line:
        on_line(f"{name}가 없어서 설치합니다 (winget, {winget_id})...")
    rc = _stream_subprocess(
        ["winget", "install", "--id", winget_id, "-e", "--accept-source-agreements", "--accept-package-agreements"],
        on_line,
    )
    refresh_path_from_registry()
    ok = shutil.which(name) is not None
    if on_line:
        on_line(f"{name} 설치 완료." if ok else f"{name} 설치에 실패했습니다 (exit {rc}).")
    return ok


def ensure_uv(on_line=None) -> bool:
    return _ensure_via_winget("uv", "astral-sh.uv", on_line)


def ensure_ffmpeg(on_line=None) -> bool:
    return _ensure_via_winget("ffmpeg", "Gyan.FFmpeg", on_line)


def check_toolchain_status() -> dict[str, bool]:
    refresh_path_from_registry()
    return {
        "uv": shutil.which("uv") is not None,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "node": shutil.which("node") is not None,
        "claude": shutil.which("claude") is not None,
        "claude-login": check_claude_auth(),
    }


def ensure_full_toolchain(on_line=None) -> bool:
    """Install everything the pipeline actually shells out to, on *this* machine: uv, ffmpeg,
    Node.js (if needed for npm) and the claude CLI. Runs in order and keeps going even if one
    step fails, so a single missing piece doesn't block the others. Returns True only if all
    four end up present."""
    ok_uv = ensure_uv(on_line)
    ok_ffmpeg = ensure_ffmpeg(on_line)
    ok_claude = ensure_claude_cli(on_line)  # also installs Node.js if missing
    return ok_uv and ok_ffmpeg and ok_claude


def check_claude_auth() -> bool:
    """Is the standalone `claude` CLI (separate from whatever is running this code) logged in?

    A fresh `npm install -g @anthropic-ai/claude-code` is NOT authenticated just because it
    installed -- it needs its own one-time `claude auth login`, independent of any other Claude
    session or app on the machine.
    """
    if not shutil.which("claude"):
        return False
    try:
        r = subprocess.run(
            _windows_safe_argv(["claude", "auth", "status"]),
            cwd=ROOT,
            env=utf8_env(),
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=15,
        )
        data = json.loads(r.stdout.strip())
        return bool(data.get("loggedIn"))
    except Exception:
        return False


def login_claude_cli(on_line=None, timeout: float = 180.0) -> bool:
    """Run `claude auth login`: opens this machine's browser for OAuth and waits for it to finish.

    Must run on the machine whose browser should open -- the whole point is that it's a one-time,
    human-in-the-browser step on wherever the GUI/exe actually launched.
    """
    if not shutil.which("claude"):
        if on_line:
            on_line("claude CLI가 설치되어 있지 않습니다. 먼저 필수 프로그램을 설치해주세요.")
        return False
    try:
        proc = subprocess.Popen(
            _windows_safe_argv(["claude", "auth", "login", "--claudeai"]),
            cwd=ROOT,
            env=utf8_env(),
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
    except OSError as exc:
        if on_line:
            on_line(f"로그인 실행 실패: {exc}")
        return False
    assert proc.stdout is not None
    for line in proc.stdout:
        if on_line:
            on_line(line.rstrip("\n"))
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        if on_line:
            on_line("로그인 대기 시간이 지났습니다 (브라우저에서 로그인을 완료했는지 확인 후 다시 시도해주세요).")
        return False
    ok = check_claude_auth()
    if on_line:
        on_line("로그인 완료." if ok else "로그인이 완료되지 않았습니다.")
    return ok


def run_claude_headless(prompt_text: str, max_budget_usd: float = 5.0, on_line=None) -> int:
    """Run `claude -p <prompt_text>` unattended, streaming stdout line by line to `on_line`.

    Returns the process exit code, or -1 if the `claude` CLI could not be found.
    """
    claude = shutil.which("claude")
    if not claude:
        if on_line:
            on_line("'claude' CLI를 찾을 수 없습니다. 설치 화면에서 claude CLI 설치가 끝났는지 확인하세요.")
        return -1
    if not check_claude_auth():
        if on_line:
            on_line("claude CLI가 로그인되어 있지 않습니다. 설치 화면에서 'Claude 로그인' 버튼을 먼저 눌러주세요.")
        return -1

    proc = subprocess.Popen(
        _windows_safe_argv(
            [
                claude,
                "-p",
                prompt_text,
                "--permission-mode",
                "bypassPermissions",
                "--max-budget-usd",
                str(max_budget_usd),
                "--output-format",
                "text",
            ]
        ),
        cwd=ROOT,
        env=utf8_env(),
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        if on_line:
            on_line(line.rstrip("\n"))
    proc.wait()
    return proc.returncode
