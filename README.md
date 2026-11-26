# Shorts Maker

주제 하나(또는 "아무거나")만 입력하면 유튜브 숏츠(9:16, 60초 이하)를 끝까지 자동으로 만들어주는 Windows 프로그램입니다.
리서치 → 대본 검수 → 상단 타이틀 → 영상/음성 생성 → 품질 검수 → 편집 → 자막 → 최종 검수까지 12개의 전담 에이전트가 사람 개입 없이 순서대로 작업하고, 마지막에만 사람이 "업로드할지"를 결정합니다.

[Claude Code](https://claude.ai/code)와 [claude-code-video-toolkit](https://github.com/digitalsamba/claude-code-video-toolkit) 위에 만들어졌습니다. 그 툴킷의 영상 제작 도구(ffmpeg, ElevenLabs, OpenArt/Higgsfield 등)를 그대로 가져다 쓰는 자동화 레이어입니다.

## 설치

### GUI (프로그래밍 지식 없이 쓰는 경우)

1. `build-exe.ps1`을 실행해 `Shorts Maker.exe`를 만듭니다 (PyInstaller, 한 번만 하면 됨):
   ```powershell
   .\build-exe.ps1
   ```
2. `Shorts Maker.exe`를 더블클릭합니다.
3. **설치** 탭에서:
   - ElevenLabs(음성): API 키 또는 MCP 연동 중 선택
   - 영상 생성: OpenArt(Claude Code MCP), Higgsfield(API 키), Higgsfield(MCP, mcp.higgsfield.ai, 유료 구독 필요) 중 선택. Higgsfield MCP는 "등록" 버튼 하나로 claude CLI에 등록되고, 다음 실행 때 브라우저 로그인(OAuth)만 한 번 더 하면 됩니다.
   - 유튜브 로그인(업로드하려면, 선택 사항)
   - "필수 프로그램" 버튼으로 uv/ffmpeg/Node.js/Claude Code CLI를 자동 설치
   - "Claude 로그인" 버튼으로 `claude` CLI 로그인

`install-shorts.bat`을 더블클릭하면 GUI 없이 터미널에서 같은 설치 과정을 진행할 수 있습니다.

### CLI (터미널에 익숙한 경우)

```powershell
cd "claude-code-video-toolkit 루트"
uv run tools/shorts_cli.py install
```

## 사용법

### GUI

`Shorts Maker.exe`의 **실행** 탭에서 주제, 영상 길이(최대 60초), 개수, 업로드 여부, 완성된 mp4를 저장할 폴더를 입력하고 시작하면 끝까지 자동으로 진행됩니다. `make-short.bat`을 더블클릭해도 같은 걸 터미널에서 할 수 있습니다.

### CLI

```powershell
uv run tools/shorts_cli.py run --topic "문어는 왜 심장이 3개나 될까?" --duration 30 --count 1 --output-dir "C:\videos"
```

| 옵션 | 설명 |
|------|------|
| `--topic` | 주제 (비워두거나 "아무거나"/"자유주제"라고 하면 AI가 직접 고름) |
| `--duration` | 영상 길이(초), 최대 60 |
| `--count` | 한 번에 만들 영상 개수 |
| `--upload` / `--no-upload` | 완성 후 유튜브에 올릴지 |
| `--output-dir` | 완성된 mp4를 복사해 둘 폴더 |

## 파이프라인 구조

`shorts-jobs/<id>/` 폴더 하나에 모든 산출물이 쌓이며, 아래 순서로 전담 에이전트가 자동 호출됩니다 (자세한 내용은 [`.claude/skills/shorts-pipeline/SKILL.md`](.claude/skills/shorts-pipeline/SKILL.md)):

1. **topic.json 작성**: 입력한 주제를 그대로 쓰거나(자유 주제면 스스로 정함)
2. **scalper**: 주제 리서치, 훅-본론-마무리 스토리보드
3. **script-qa-looper**: 대본이 실제로 주제를 다루는지, 과장은 없는지 검수 (최대 3루프)
4. **title-picker / title-qa-looper**: 화면 상단에 들어갈 타이틀 문구 선정 및 검수 (최대 3루프)
5. **spawner / tts-spawner**: OpenArt 또는 Higgsfield로 영상 생성, ElevenLabs로 음성 생성
6. **qa-tts-looper**: 음성이 자연스러운지 검수 (최대 3루프)
7. **qa-looper**: 파일 유효성, 길이 정합성 등 전반 검수 (최대 5루프)
8. **editor**: 9:16 편집과 상단 타이틀 번인
9. **subtitles / subtitles-qa-looper**: 자막 생성, 번인 및 정합성 검수 (최대 5루프)
10. **publisher**: 최종 품질 검수(규격, 길이, 내용 정합성, 전체적인 자연스러움), 승인 후 유튜브 업로드는 채널을 보여주고 사람 승인을 받은 뒤에만 진행 (최대 7루프)

## 예시

[examples/flamingo-one-leg](examples/flamingo-one-leg)에 실제로 돌린 결과물 두 개를 올려뒀습니다.

- [source-clip.mp4](examples/flamingo-one-leg/source-clip.mp4): OpenArt가 만든 가공 전 원본 영상(음성, 타이틀, 자막 없음)
- [final.mp4](examples/flamingo-one-leg/final.mp4): 같은 작업에서 나온 최종 완성본(21.9초, 내레이션/상단 타이틀/자막 전부 포함)

주제는 "플라밍고는 왜 한 다리로 서있을까?"였고, 중간에 publisher가 한 씬의 내용 불일치를 실제로 잡아내서 재생성한 과정까지 [examples/flamingo-one-leg/README.md](examples/flamingo-one-leg/README.md)에 적어뒀습니다.

## 더 알아보기

이 저장소는 [claude-code-video-toolkit](https://github.com/digitalsamba/claude-code-video-toolkit)을 통째로 기반으로 하고 있어서, Shorts Maker 외에도 Remotion 기반 영상 템플릿, 브랜드 프로필, FFmpeg/ElevenLabs/Blender 등 다양한 도구가 `tools/`, `templates/`, `docs/`에 함께 들어 있습니다. 그 쪽을 쓰고 싶다면 원본 저장소의 README와 `docs/`를 참고하세요. 라이선스는 MIT입니다 ([LICENSE](LICENSE)).
