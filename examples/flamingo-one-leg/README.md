# flamingo-one-leg: Shorts Maker 예시

Shorts Maker로 주제 하나("플라밍고는 왜 한 다리로 서있을까?")를 끝까지 자동으로 돌린 실제 결과물입니다. 조작 없이 이 저장소의 12개 에이전트가 만든 실제 파일 두 개를 그대로 올려뒀습니다.

## source-clip.mp4

OpenArt(PixVerse V6, text2video)가 만든 1번 씬의 원본 영상입니다. 음성, 상단 타이틀, 자막이 전부 없는 **가공 전 영상 소스** 상태입니다. spawner 단계가 이런 클립을 씬 개수만큼 받아옵니다.

## final.mp4

같은 작업에서 나온 **최종 완성본**(21.9초)입니다. scalper가 쓴 대본에 ElevenLabs 내레이션을 입히고, title-picker가 정한 상단 타이틀("플라밍고는 왜 외발로 설까?")을 번인하고, subtitles가 자막을 붙인 뒤, publisher가 검수한 결과입니다.

실제로 publisher는 1차 검수에서 반려했습니다: 04번 씬 내레이션("죽은 플라밍고도 한 다리로 섰다는 게 밝혀졌어요")이 나오는 동안 화면엔 양다리가 다 보여서 내용과 안 맞았습니다. 그 씬만 OpenArt로 다시 생성(한 다리만 보이도록 프롬프트 수정)하고 editor/subtitles를 다시 거친 뒤 2차 검수에서 승인됐습니다. `final.mp4`는 그 승인된 버전입니다.

## 어떻게 만들어졌는지

| 단계 | 담당 | 비고 |
|------|------|------|
| 리서치/대본 | scalper | 플라밍고 한 다리 자세에 관한 2010년/2017년 실제 연구 2건을 근거로 구성 |
| 대본 검수 | script-qa-looper | 1루프에 통과 |
| 상단 타이틀 | title-picker / title-qa-looper | "플라밍고는 왜 외발로 설까?", 자연스러운 한국어 종결 기준으로 재작성 |
| 영상 생성 | spawner (OpenArt, PixVerse V6 text2video, 9:16 1080p) | 5개 씬, 04번 씬은 publisher 반려로 1회 재생성 |
| 음성 생성 | tts-spawner (ElevenLabs) | 5개 씬 내레이션 + 전체 이어붙인 오디오 |
| 음성 검수 | qa-tts-looper | 1루프에 통과 |
| 전반 검수 | qa-looper | 오디오가 계획보다 짧아 영상을 오디오 길이에 맞춰 트리밍하도록 editor에 지시 |
| 편집 | editor | 9:16 조립 + 상단 타이틀 번인 |
| 자막 | subtitles / subtitles-qa-looper | ElevenLabs Scribe로 단어 단위 타이밍, 1차 반려(읽기 속도) 후 2차 통과 |
| 최종 검수 | publisher | 1차 반려(04번 씬 내용 불일치) 후 재생성, 2차 승인 |

이 저장소의 `.claude/agents/`와 `.claude/skills/shorts-pipeline/SKILL.md`에 각 단계의 정확한 기준과 루프 규칙이 적혀 있습니다. 유튜브 업로드는 하지 않았습니다(사람 승인이 필요한 단계라 이 예시에서는 진행하지 않음).
