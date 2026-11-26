#!/usr/bin/env python3
"""Shorts pipeline installer & runner (terminal version -- see shorts_gui.py for the windowed app).

    uv run tools/shorts_cli.py install
    uv run tools/shorts_cli.py run
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from win_encoding import ensure_utf8_output  # noqa: E402
from shorts_common import (  # noqa: E402
    ENV_PATH,
    ROOT,
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
    run_uv,
    set_env_var,
    slugify,
    verify_job_topic,
)


def prompt(msg: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{msg}{suffix}: ").strip()
    return val or (default or "")


def prompt_yes_no(msg: str, default: bool) -> bool:
    d = "Y/n" if default else "y/N"
    val = input(f"{msg} ({d}): ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes", "예", "ㅇ", "응")


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

def cmd_install(_: argparse.Namespace) -> int:
    print("=== Shorts 파이프라인 설치 ===\n")

    print("[1/4] uv sync로 의존성을 설치합니다...")
    subprocess.run(["uv", "sync", "--extra", "youtube", "--extra", "prosody"], cwd=ROOT, check=False)

    print("\n[2/4] 음성 생성 서비스: ElevenLabs API 키 또는 MCP")
    eleven_choice = prompt("  어느 쪽을 쓸까요? (api/mcp)", "api").lower()
    if eleven_choice.startswith("m"):
        print("  ElevenLabs도 Claude Code에서 /mcp 로 직접 연결해주세요 -- 이 스크립트가 대신 해줄 수는 없습니다.")
        print("  연결되어 있으면 API 키 없이도 파이프라인이 자동으로 그쪽을 씁니다.")
    else:
        print("  https://elevenlabs.io/app/settings/api-keys 에서 키를 발급받으세요.")
        key = getpass("  ELEVENLABS_API_KEY (입력은 화면에 표시되지 않습니다, 건너뛰려면 Enter): ").strip()
        if key:
            set_env_var("ELEVENLABS_API_KEY", key)
            print("  저장했습니다.")
        else:
            print("  건너뛰었습니다 -- 나중에 .env에 직접 추가하거나 install을 다시 실행하세요.")

    print("\n[3/4] 영상 생성 서비스: OpenArt 또는 Higgsfield")
    choice = prompt("  어느 쪽을 쓸까요? (openart/higgsfield-api/higgsfield-mcp)", "higgsfield-api").lower()
    if choice.startswith("o"):
        print("  OpenArt는 API 키가 아니라 Claude Code의 MCP 커넥터(OAuth)로 연결됩니다.")
        print("  Claude Code 세션에서 /mcp (또는 Claude 데스크탑 앱의 커넥터 설정)를 열어")
        print("  OpenArt 계정으로 로그인해서 연결해주세요 -- 이 스크립트가 대신 해줄 수는 없습니다.")
        input("  연결을 마쳤으면 Enter를 눌러 계속하세요 (지금 건너뛰려면 그냥 Enter)...")
    elif "mcp" in choice:
        print("  Higgsfield의 공식 호스팅 MCP(mcp.higgsfield.ai)를 claude CLI에 등록합니다 (API 키 불필요).")
        print("  유료 구독 계정이 필요하고, 등록 후 다음에 claude를 쓸 때 브라우저 로그인(OAuth)이 한 번 더 필요합니다.")
        if prompt_yes_no("  지금 등록할까요?", True):
            connect_higgsfield_mcp(on_line=print)
    else:
        key_id = prompt("  HIGGSFIELD_KEY_ID (console.higgsfield.ai에서 발급)")
        key_secret = getpass("  HIGGSFIELD_KEY_SECRET (입력이 화면에 표시되지 않습니다): ").strip()
        if key_id and key_secret:
            set_env_var("HIGGSFIELD_KEY_ID", key_id)
            set_env_var("HIGGSFIELD_KEY_SECRET", key_secret)
            print("  저장했습니다.")
        else:
            print("  건너뛰었습니다.")

    print("\n[4/4] YouTube 연결")
    print("  처음이라면 Google Cloud Console에서 OAuth 클라이언트(Desktop app)를 만들고")
    print("  client_secret_*.json을 다운로드해야 합니다 (docs/youtube-upload.md 참고).")
    secrets_path = prompt("  client_secret json 파일의 절대경로 (이미 설정돼 있으면 Enter로 건너뛰기)")
    if secrets_path:
        p = Path(secrets_path)
        if not p.is_file():
            print(f"  경고: 파일을 찾을 수 없습니다 ({secrets_path}).")
        set_env_var("YOUTUBE_CLIENT_SECRETS_FILE", str(p))
    if prompt_yes_no("  지금 유튜브 로그인을 진행할까요? (브라우저가 열립니다)", False):
        subprocess.run(
            ["uv", "run", "--extra", "youtube", "tools/youtube_upload.py", "--auth", "--account", "default"],
            cwd=ROOT,
        )

    print("\n[추가] 필수 프로그램 (uv / ffmpeg / Node.js / Claude CLI)")
    status = check_toolchain_status()
    missing = [name for name, ok in status.items() if not ok]
    if not missing:
        print("  전부 이미 설치되어 있습니다.")
    elif prompt_yes_no(f"  누락: {', '.join(missing)}. 지금 설치할까요?", True):
        ensure_full_toolchain(on_line=print)

    print("\n[추가] Claude 로그인")
    if check_claude_auth():
        print("  이미 로그인되어 있습니다.")
    elif prompt_yes_no("  claude CLI가 로그인되어 있지 않습니다. 지금 로그인할까요? (브라우저가 열립니다)", True):
        login_claude_cli(on_line=print)

    print("\n설치 단계를 마쳤습니다. 연결 상태를 확인합니다...\n")
    print("  ElevenLabs:", "OK" if get_env_var("ELEVENLABS_API_KEY") else "미설정")
    print(
        "  Higgsfield (API 키):",
        "OK" if get_env_var("HIGGSFIELD_KEY_ID") and get_env_var("HIGGSFIELD_KEY_SECRET") else "미설정",
    )
    print("  Higgsfield (MCP):", "등록됨" if check_higgsfield_mcp() else "미등록")
    print("  (OpenArt MCP나 위 둘 중 하나만 있으면 됩니다.)")
    data = check_youtube()
    ch = (data or {}).get("channel")
    print("  YouTube:", f"OK ({ch['title']})" if ch else f"미연결 ({(data or {}).get('auth') or (data or {}).get('error') or '확인 필요'})")
    final_status = check_toolchain_status()
    print("  필수 프로그램:", "전부 OK" if all(final_status.values()) else f"누락: {', '.join(k for k, v in final_status.items() if not v)}")
    return 0


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> int:
    print("=== Shorts 자동 제작 ===\n")

    topic = args.topic or ""
    while not topic:
        topic = prompt("주제 (자유 주제)")

    duration = args.duration
    while duration is None or not (5 <= duration <= 60):
        raw = prompt("영상 길이 (초, 최대 60)", "30")
        try:
            duration = int(raw)
        except ValueError:
            duration = None
        if duration is not None and not (5 <= duration <= 60):
            print("  5~60 사이의 숫자를 입력해주세요.")
            duration = None

    count = args.count
    while count is None or count < 1:
        raw = prompt("몇 개 만들까요? (영상 개수)", "1")
        try:
            count = int(raw)
        except ValueError:
            count = None
        if count is not None and count < 1:
            count = None

    upload = args.upload if args.upload is not None else prompt_yes_no("완성되면 유튜브에 업로드할까요?", False)

    output_dir = Path(args.output_dir).expanduser() if args.output_dir else None
    if output_dir is None:
        raw = prompt("완성된 mp4를 복사해 둘 폴더 (비워두면 shorts-jobs/<id>/output/ 에만 남김)")
        output_dir = Path(raw).expanduser() if raw else None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    channel_label = None
    if upload:
        print("\n연결된 유튜브 채널을 확인합니다...")
        data = check_youtube()
        ch = (data or {}).get("channel")
        if not ch:
            print("  연결된 채널이 없습니다 -- 먼저 `uv run tools/shorts_cli.py install`로 로그인해주세요.")
            print("  이번 실행은 업로드 없이 진행합니다.")
            upload = False
        else:
            channel_label = f"{ch['title']} ({ch['id']})"
            if not prompt_yes_no(f"  '{channel_label}' 채널에 업로드하는 게 맞습니까?", True):
                print("  업로드는 생략하고 영상 제작만 진행합니다.")
                upload = False

    print(f"\n주제: {topic}")
    print(f"길이: {duration}s / 개수: {count}개 / 업로드: {('예 (' + channel_label + ')') if upload else '아니오'}")
    print(f"저장 위치: {output_dir if output_dir else '(기본 위치만)'}")
    if not prompt_yes_no("이대로 시작할까요?", True):
        print("취소했습니다.")
        return 1

    if not shutil.which("claude"):
        print("\n'claude' CLI를 찾을 수 없습니다. `uv run tools/shorts_cli.py install`을 먼저 실행해주세요.")
        return 1
    if not check_claude_auth():
        print("\nclaude CLI가 로그인되어 있지 않습니다. `uv run tools/shorts_cli.py install`에서 로그인해주세요.")
        return 1

    import time

    slug = slugify(topic)
    for i in range(1, count + 1):
        job_id = new_job_id(slug, i, count)
        print(f"\n[{i}/{count}] shorts-jobs/{job_id} 작업을 시작합니다...")

        prompt_text = build_pipeline_prompt(job_id, topic, duration, upload, channel_label)
        run_started_at = time.time()
        rc = run_claude_headless(prompt_text, on_line=print)

        if rc != 0:
            print(f"  [{i}/{count}] claude 세션이 비정상 종료됐습니다 (exit {rc}) -- shorts-jobs/{job_id} 폴더를 확인하세요.")
            continue

        # claude -p가 exit 0으로 끝났다고 작업이 실제로 성공했다는 뜻은 아니다 -- 진짜 결과물이
        # 있는지로 성공 여부를 판단한다.
        src = find_final_mp4(job_id, run_started_at)
        if src is None:
            print(f"  [{i}/{count}] 세션은 끝났지만 영상을 만들지 못한 것 같습니다 -- shorts-jobs/{job_id} 폴더를 확인하세요.")
            continue

        actual_job = src.parent.parent.name
        if actual_job != job_id:
            match = verify_job_topic(src.parent.parent, topic)
            if match is False:
                print(
                    f"  [{i}/{count}] 'shorts-jobs/{actual_job}'에서 영상을 찾았지만 주제가 요청하신 "
                    f"'{topic}'와 달라서 이번 요청 결과로 보지 않습니다 -- 이번 요청은 사실상 실패입니다. "
                    f"shorts-jobs/{job_id} 폴더를 직접 확인하세요."
                )
                continue
            print(f"  참고: 에이전트가 지시한 폴더 대신 'shorts-jobs/{actual_job}'에 결과를 만들었습니다.")

        print(f"  [{i}/{count}] 완료 -- {src}")
        if output_dir is not None:
            dest = output_dir / f"{job_id}.mp4"
            dest.write_bytes(src.read_bytes())
            print(f"  -> {dest} 로 복사했습니다.")

    return 0


def main() -> int:
    ensure_utf8_output()
    refresh_path_from_registry()
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("install", help="ElevenLabs / OpenArt 또는 Higgsfield / YouTube 연결 설정")

    run_p = sub.add_parser("run", help="주제로 숏츠를 자동 제작")
    run_p.add_argument("--topic")
    run_p.add_argument("--duration", type=int)
    run_p.add_argument("--count", type=int)
    run_p.add_argument("--upload", action=argparse.BooleanOptionalAction, default=None)
    run_p.add_argument("--output-dir", help="완성된 mp4를 복사해 둘 폴더")

    args = ap.parse_args()
    if args.cmd == "install":
        return cmd_install(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
