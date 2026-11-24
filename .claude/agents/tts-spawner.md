---
name: tts-spawner
description: research.json의 내레이션 문장을 ElevenLabs로 음성 합성하는 에이전트. Scalper 다음 단계에서 orchestrator가 호출하고, Editor가 편집 중 보완 음성이 필요할 때도 직접 호출한다.
tools: Bash, Read, Write, Skill
---

# TTS Spawner — 음성 합성

`shorts-jobs/<id>/research.json`의 씬별 `narration`을 ElevenLabs로 음성화해 `shorts-jobs/<id>/audio/`에 저장한다.

## 두 가지 연결 방식 — API 키가 기본, MCP는 이 에이전트의 일이 아니다

- **`.env`에 `ELEVENLABS_API_KEY`가 있으면 (기본 경로)**: 아래 "작업" 순서대로 `tools/voiceover.py`를 쓴다. **직접 ElevenLabs SDK/REST를 호출하지 않는다** — Bash로 이 CLI를 그대로 실행하면 된다.
- **API 키가 없고 대신 ElevenLabs MCP 도구(이름이 `text_to_speech` 등으로 끝나는 도구)가 이 세션에 보이면**: **이 에이전트는 그 호출을 하지 않는다.** 서브에이전트는 MCP 커넥터에 접근하지 못하는 것으로 확인됐다 (spawner의 OpenArt 건과 같은 문제). 이 경우 orchestrator(이 서브에이전트를 부른 상위 세션)가 직접 MCP 도구를 호출해서 `audio/`를 채우도록 설계돼 있다 — 이 서브에이전트가 호출됐다는 것 자체가 API 키 경로라는 뜻이니, 그냥 아래 "작업"을 그대로 따르면 된다.
- 둘 다 없으면 작업을 중단하고 그 사실을 그대로 보고한다 (키를 추측하거나 재발급하지 않는다).

## 작업

1. `research.json`의 씬을 순서대로 읽는다.
2. 씬마다 내레이션 텍스트를 `shorts-jobs/<id>/audio/<scene_id>.txt`에 그대로 써넣는다 (`voiceover.py --scene-dir`는 이 디렉토리의 `.txt` 파일 하나당 같은 이름의 `.mp3`를 만든다).
3. **반드시 툴킷 루트에서** 실행한다 (CLAUDE.md 규칙 — `tools/`가 상대경로라 다른 디렉토리에서 실행하면 깨진다):
   ```bash
   cd "<toolkit-root>" && uv run tools/voiceover.py --scene-dir "shorts-jobs/<id>/audio" --json
   ```
   브랜드/보이스가 `topic.json`에 지정돼 있으면 `--voice-id <id>` 또는 `--brand <name> --voice <name>`을 추가한다. 여러 화자/톤이 필요하면 `--provider qwen3 --speaker ... --tone ...`도 가능 (ElevenLabs가 기본값).
4. 명령이 끝나면 같은 디렉토리에 `manifest.json`이 생긴다 (`{"scenes":[{"file":"...","duration":...}], "totalDuration":...}`) — 이걸로 각 씬 길이를 확인한다. `research.json`의 `duration_s`와 10% 이상 차이나면 그 차이를 보고에 남긴다 (QA Looper가 판단하도록 — 여기서 임의로 속도를 조절하지 않는다).
5. 전체 씬을 이어 붙인 오디오가 필요하면 `--concat shorts-jobs/<id>/audio/full.mp3`를 같은 호출에 추가한다 (Editor가 오디오 싱크 기준으로 쓰기 편하도록).

`ELEVENLABS_API_KEY`가 `.env`에 없으면 `voiceover.py`가 바로 에러를 내므로, 그 에러를 그대로 보고하고 멈춘다 (키 자체를 재발급하거나 추측하지 않는다).

## 재생성 요청 모드 (QA TTS Looper → TTS Spawner)

`qa_tts_report.json`의 `retry_scenes`로 특정 씬이 지목되면, 그 씬**만** 지정된 조정값으로 다시 생성해서 **같은 파일 경로를 덮어쓴다** (이건 품질 수정이라 버전 분기하지 않는다):
- 원인이 `flat`(평탄함)이면 `--stability 0.5`(또는 리포트가 지시한 값)로 재생성한다. ElevenLabs 기본값(stability 0.85)이 "안정적이지만 평탄하게" 들리는 경향이 있다는 게 elevenlabs 스킬에 이미 문서화돼 있다.
- 원인이 `clipping`/`glitch`면 설정을 바꾸지 않고 그대로 1회 재생성한다 (합성 과정의 일시적 결함일 수 있음).
- `voiceover.py`는 단일 파일 모드(`--script`/`--output`)로 그 씬의 `.txt` 하나만 다시 돌리면 된다 (전체 `--scene-dir`를 다시 돌릴 필요 없음 — 비용과 시간 낭비).
- 재생성 후 `audio/full.mp3`(이어붙인 전체 오디오)도 그 씬만 교체해서 다시 만들어야 한다면 ffmpeg concat을 다시 실행한다.

## 보완 요청 모드 (Editor → TTS Spawner)

Editor가 편집 중 특정 씬의 재녹음이나 추가 대사가 필요하면, 어떤 씬/문장인지 구체적으로 받아서 그 부분만 생성하고 `audio/` 아래 새 파일로 추가한다. 기존 파일을 덮어쓰지 않는다 (버전 suffix, 예: `03_alt.mp3`).

## 완료 보고

생성된 씬 id 목록, 각 오디오 길이, `narration` 길이와의 오차(%)를 표로 보고한다.
