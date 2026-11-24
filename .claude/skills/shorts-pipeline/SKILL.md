---
name: shorts-pipeline
description: 주제 하나(또는 "anything"/"자유주제" 같은 자유 주제 요청)로 유튜브 숏츠를 자동 제작하는 파이프라인(topic.json 직접 작성 → scalper → script-qa-looper → [title-picker → title-qa-looper] → spawner/[tts-spawner → qa-tts-looper] → qa-looper → editor → [subtitles → subtitles-qa-looper] → publisher, 12개 서브에이전트)을 지휘한다. 사용자가 "이 주제로 숏츠 만들어줘", "자동으로 영상 제작해줘" 같은 요청을 하면 이 스킬을 따른다. 실제 에이전트 호출은 Agent 도구로 이름을 지정해서 한다.
---

# Shorts Pipeline — 오케스트레이션

이 스킬은 코드가 아니라 **진행 순서와 루프 규칙**이다. 각 단계는 `.claude/agents/`에 정의된 서브에이전트를 `Agent` 도구로 호출해서 수행하고, 상태는 전부 파일로 주고받는다(에이전트 간 메모리 공유가 없으므로). **단, topic.json 작성(1번)은 예외다** — orchestrator가 Agent 도구 없이 직접 쓴다 (이유는 1번 참고).

## 작업 폴더

```
shorts-jobs/<id>/
  topic.json           입력 (주제, 길이, 톤, 보이스/브랜드)
  research.json         ← scalper
  script_qa_report.json  ← script-qa-looper (대본이 주제를 실제로 다루는지)
  title.json              ← title-picker (상단 번인 타이틀 문구)
  title_qa_report.json   ← title-qa-looper (타이틀이 주제/대본과 맞는지, 길이)
  assets/                ← spawner
  audio/                 ← tts-spawner
  qa_tts_report.json     ← qa-tts-looper (음성 자연스러움)
  qa_report.json         ← qa-looper (파일/길이 전반)
  output/cut_v*.mp4      ← editor (상단 타이틀 번인, 자막 없는 편집본)
  output/edit.json       ← editor (트림 구간 + 씬별 누적 시작 시각)
  output/final_v*.mp4    ← subtitles (자막 번인된 최종본)
  output/_work/subs_v*.ass, words_<scene>.json  ← subtitles
  subtitles_qa_report.json ← subtitles-qa-looper
  publish_report.json    ← publisher
```

`<id>`는 타임스탬프나 주제 슬러그로 orchestrator(현재 세션)가 정한다. 이 폴더는 `jobs/`(toolkit 자체의 video_job 시스템)와 겹치지 않도록 `shorts-jobs/`로 분리한다.

## 순서

1. **입력 정리 — topic.json은 orchestrator가 Agent 도구 없이 직접 쓴다.** 사용자 요청에서 주제/목표 길이/톤/보이스를 뽑는다. 부족한 정보(길이/톤/보이스)는 합리적 기본값(30초, ko, 정보/흥미 톤)으로 채운다 — **이 정도 공백은 사용자에게 되묻지 않는다.**
   - **구체적인 주제가 주어졌으면(= `"anything"`/`"자유주제"`/`"아무거나"`/빈 문자열이 아니면), topic-picker를 호출하지 않는다.** orchestrator(지금 이 세션)가 그 주제 문자열을 **토씨 하나 바꾸지 않고 그대로** `shorts-jobs/<id>/topic.json`에 직접 써라 (Write 도구로, Agent 도구 아님). 요약·순화·재해석하지 않는다.
     - 이렇게 바꾼 이유: topic-picker를 서브에이전트로 호출하면, 그 호출 프롬프트에 주제를 명시적으로 옮겨 적어야 하는데, 이 relay 단계에서 반복적으로 주제가 누락돼 topic-picker가 "자유 주제 요청"으로 오해하고 완전히 다른 주제를 멋대로 고르는 사고가 **세 번 연속** 일어났다. orchestrator 자신은 사용자 요청을 직접 읽으므로 주제를 놓칠 일이 없다 — 그러니 이 경우엔 아예 중간 전달 단계를 두지 않는다.
   - **자유 주제 요청일 때만** (`"anything"`/`"자유"`/`"자유주제"`/`"아무거나"`/`free`/`random`/빈 문자열): `.claude/agents/topic-picker.md`를 Read로 읽고, 그 기준(좋은 숏츠 주제의 기준, 중복 회피 등)에 따라 **orchestrator가 직접** 구체적인 주제를 정해서 `topic.json`을 쓴다. 이 경우도 Agent 도구로 topic-picker를 호출하지 않는다 — 문서만 참고하고 실행은 orchestrator가 한다.
   - **주제 자체를 다룰 수 없다고 판단되는 경우만**(명백한 불법행위 방법 안내 등 — 드물어야 한다) `topic.json`을 쓰지 말고 멈춰서 이유를 명확히 보고한다. "이 주제는 별로니까" 정도의 이유로 다른 주제로 바꾸는 것은 절대 허용되지 않는다 — 이게 과거 세 번의 사고 모두의 원인이었다.
   - 끝나면 2번으로.
2. **scalper** 호출 → `research.json` 생성.
3. **script-qa-looper** 호출 → `script_qa_report.json`. 대본이 실제로 주제를 다루는지, 과장/구조 문제는 없는지 검사한다 — **영상/음성을 만들기 전(돈 쓰기 전)에 걸러내는 단계**라서 중요하다.
   - `verdict: "retry"`면, `issues`를 들고 **scalper만** 지적된 씬 위주로 다시 호출하고(전체 재작성 아님) 다시 script-qa-looper를 돌린다.
   - 이 루프는 **최대 3회**. 3회에도 `retry`면 `verdict: "escalate"`로 받아 어떤 문제가 계속 남는지 보고하고 멈춘다.
   - `verdict: "pass"`면 4번으로.
4. **title-picker** 호출 → `title.json` (영상 상단에 번인할 짧은 타이틀 문구). `topic.json`/`research.json`을 읽어서 정하므로 파일 경로만 넘기면 된다.
5. **title-qa-looper** 호출 → `title_qa_report.json`. 타이틀이 주제/대본과 맞는지, 화면에 들어갈 분량인지, 낚시성 문구가 아닌지 검사한다.
   - `verdict: "retry"`면, `issues`를 들고 **title-picker만** 다시 호출(전체 재작성 아님, 지적된 부분만) 하고 다시 title-qa-looper를 돌린다.
   - 이 루프는 **최대 3회**. 3회에도 `retry`면 `verdict: "escalate"`로 받아 어떤 문제가 계속 남는지 보고하고 멈춘다.
   - `verdict: "pass"`면 6번으로.
6. **spawner**와 **tts-spawner**를 호출한다 (서로 독립적이라 순서는 상관없음; 병렬로 맡겨도 된다) → `assets/`, `audio/` 생성.
   - **예외(헤드리스/무인 배치일 때 특히 중요)**: spawner 서브에이전트는 OpenArt MCP 도구에 접근하지 못하는 경우가 있다(권한이 아니라 연결 자체가 안 됨 — subagent가 MCP 커넥터를 상속받지 못하는 것으로 보임). OpenArt 경로가 필요하면 spawner를 호출하는 대신 **orchestrator(지금 이 세션)가 `.claude/agents/spawner.md`의 "OpenArt MCP 호출 흐름"을 직접 읽고 그대로 수행**해서 `assets/`를 채운다. Higgsfield 폴백/재생성 모드/보고는 spawner.md대로 spawner 서브에이전트에 맡겨도 된다.
   - **같은 예외가 TTS에도 적용된다**: `.env`에 `ELEVENLABS_API_KEY`가 있으면 tts-spawner를 그대로 호출(Bash라서 서브에이전트도 문제없이 쓴다). 키가 없고 ElevenLabs MCP 도구만 보이면, tts-spawner 대신 **orchestrator가 직접** 그 MCP 도구를 호출해서 `audio/`를 채운다.
7. **tts-spawner가 끝나는 즉시 (spawner와는 독립적으로) qa-tts-looper** 호출 → `qa_tts_report.json`. 음성이 평탄(로봇처럼 들림)하거나 클리핑/글리치가 있는지 수치로 검사한다.
   - `verdict: "retry"`면, `retry_scenes`의 씬만 **tts-spawner에게 지정된 설정(예: stability 낮춤)으로 재생성**을 요청하고 다시 qa-tts-looper를 돌린다.
   - 이 루프는 **최대 3회**. 3회에도 `retry`면 `verdict: "escalate"`로 받아 사용자에게 어떤 씬의 어떤 수치가 계속 문제인지 보여주고, 직접 들어보고 판단해달라고 요청한 뒤 멈춘다 (이 체크는 proxy일 뿐 사람의 청취를 대체하지 않는다).
   - `verdict: "pass"`면 8번으로. spawner가 아직 안 끝났으면 끝날 때까지 기다린다.
8. **qa-looper** 호출 → `qa_report.json` (파일 유효성, 씬 개수, 길이 정합성 등 전반적 검증 — 음성 자연스러움은 이미 7번에서, 대본 내용은 이미 3번에서, 타이틀은 이미 5번에서 처리됐으므로 다시 보지 않는다).
   - `verdict: "retry"`면, `retry_scenes`에 지목된 에이전트만 그 씬 id로 다시 호출하고 **6번부터 다시** (단, 해당 에이전트만; tts-spawner가 다시 불려야 하면 그다음 7번도 다시 거친다).
   - 이 루프는 **최대 5회**(`qa_report.json.loop_count` 기준). 5회에도 `retry`면 사용자에게 어떤 씬이 계속 실패하는지 보고하고 중단, 사용자 지시를 기다린다.
   - `verdict: "pass"`면 9번으로.
9. **editor** 호출 → `output/cut_v1.mp4`(상단 타이틀 번인, 자막 없는 편집본) + `output/edit.json`(씬별 누적 시작 시각).
10. **subtitles** 호출 → `output/final_v1.mp4`(자막 번인) + `output/_work/subs_v1.ass`.
11. **subtitles-qa-looper** 호출 → `subtitles_qa_report.json`.
    - `verdict: "retry"`면, `issues`를 들고 **subtitles만 다시 호출**(`cut_v<N>.mp4`는 재사용, editor는 부르지 않는다) → 같은 `final_v<N>.mp4`를 자막만 다시 입혀서 재생성 → 다시 subtitles-qa-looper.
    - 이 루프는 **5회**. 5회에도 `retry`면 `verdict: "escalate"`로 받아 사용자에게 어떤 씬의 자막이 계속 문제인지 보여주고 멈춘다.
    - `verdict: "pass"`면 12번으로.
12. **publisher** 호출 → `publish_report.json`. 포맷/규격/길이/내용 정합성(상단 타이틀이 실제로 보이는지 포함)에 더해 **전체적인 자연스러움**(씬 전환, 내레이션-비주얼 싱크, 전체 리듬)도 본다.
    - `verdict: "reject"`면 `issues`의 `area`를 보고 돌려보낼 곳을 정한다:
      - `area: "subtitle"` → **subtitles**를 다시 호출(10번부터 다시).
      - `area: "title"`(타이틀이 잘림/겹침 등 번인 위치 문제, 문구 자체 문제 아님) → **editor**를 다시 호출(9번부터 다시, `title.json` 문구는 유지).
      - `area: "editing"`/`"visual"`/`"audio"` → **editor**를 다시 호출(9번부터 다시 — editor가 새 `cut_v<N+1>.mp4`를 만들면 subtitles·subtitles-qa-looper도 그 위에서 다시 거친다).
      - `area: "content"`(내레이션과 비주얼이 안 맞음) → 지목된 씬만 **spawner**(OpenArt 경로면 orchestrator 자신)로 재생성한 뒤, 그 위에서 9번(editor)부터 다시 거친다.
    - 이 루프는 **최대 7회**. 7회에도 `reject`면 사용자에게 어떤 버전까지 시도했고 무엇이 문제인지 요약해서 보고하고 멈춘다.
    - `verdict: "approved"`면 완료.
13. **완료 보고**: 최종 mp4 경로, 총 소요 루프 수(Script QA/Title QA/QA TTS/QA/Subtitles QA/Publisher 각각), 그리고 업로드 의사를 묻는다. **실제 유튜브 업로드는 사용자가 명시적으로 요청할 때만**, 그리고 **항상 publisher가 먼저 연결된 유튜브 채널 정보를 조회해서 보여주고 그 채널이 맞는지 확인받은 뒤에만** 진행한다 (publisher.md의 "게시 단계" 참고).

## 중요 원칙

- 각 단계 호출 시 이전 산출물 경로(`shorts-jobs/<id>/...`)를 프롬프트에 명시해서 넘긴다 — 에이전트는 대화 맥락을 공유하지 않는다.
- 루프 중 재호출은 **문제가 지적된 부분만** 다시 시키는 것이 원칙이다 (scalper/spawner/tts-spawner는 씬 단위, editor/subtitles는 버전 단위). 전체 재실행은 비용·시간 낭비이므로 지양한다 — 특히 자막 문제로는 **절대 editor를 다시 부르지 않는다** (영상 재렌더는 불필요한 비용).
- 여섯 루프 한도(Script QA 3회, Title QA 3회, QA TTS 3회, QA 5회, Subtitles QA 5회, Publisher 7회)에 도달해 escalate 상태가 되면, 사람이 있는 세션에서는 사람에게 보고하고 다음 지시를 기다린다. **무인 배치(아래 참고)로 돌고 있을 때는 아무도 그 질문에 답하지 않는다** — escalate 상태를 `shorts-jobs/<id>/`에 이미 적어뒀다면(각 에이전트가 자기 리포트 json에 적는다) 그걸로 충분하다, 세션은 그 상태를 요약해서 보고하고 끝내면 된다. "기다린다"는 세션을 중단하지 않고 계속 열어두라는 뜻이 아니다.
- 업로드/게시처럼 외부에 공개되는 행동은 이 파이프라인의 자동 루프 범위 밖이다 — 항상 별도 승인(무인 배치 모드에서 사용자가 사전에 업로드를 명시적으로 승인한 경우는 publisher.md의 예외를 따른다).

## 무인 배치 모드 (사람이 중간에 답할 수 없을 때)

이 파이프라인은 종종 사람이 지켜보지 않는 배치 실행(`claude -p`, 헤드리스)으로 돌아간다. 그런 실행에서 **"주제를 알려주세요", "~해도 될까요?", "다음 중 하나를 선택해주세요" 같은 질문을 출력하고 멈추는 것은 이 스킬의 오작동이다** — 질문해도 답해줄 사람이 없으므로 그 세션은 그대로 멈춰버린다.

- 주제가 비어있거나 모호하면 **topic-picker**가 스스로 정한다 — 사용자에게 되묻지 않는다. 하지만 **구체적인 주제가 주어졌는데 orchestrator가 "이게 더 낫겠다"며 다른 주제로 바꾸는 건 되묻지 않는 것과 다른 문제다 — 금지다.** 질문 없이 진행하는 것과 사용자 요청을 조용히 무시하는 것은 다르다. 주제 자체가 정말 다룰 수 없다고 판단되면(topic-picker.md 참고) 다른 주제로 바꿔치기하지 말고 멈춰서 그 이유를 보고해라.
- **작업 폴더도 마찬가지로 임의로 바꾸지 않는다.** orchestrator가 지정한 `shorts-jobs/<id>`가 아닌 다른 이름(타임스탬프 등)으로 새 폴더를 만들거나 기존 폴더를 대신 쓴 적이 있었다 — 이러면 실행을 띄운 프로그램이 결과물을 영영 못 찾는다. topic-picker부터 publisher까지 모든 단계가 정확히 그 폴더 하나만 쓴다.
- 그 외 모든 단계에서 판단이 애매한 지점(씬 개수, 보이스 톤, 트림 구간, 어떤 모델을 쓸지 등)은 각 에이전트 정의에 적힌 기본값/판단 기준대로 **스스로 결정하고 진행한다.** 결정한 이유는 최종 보고에 한 줄로 남기면 충분하다 — 질문으로 바꾸지 않는다. (주제·작업 폴더는 이 "스스로 결정"의 대상이 아니다 — 위 두 항목 참고.)
- 정말로 더 진행이 불가능한 경우(루프 한도 초과, 크레덴셜 누락, 파일 손상, 주제 자체를 다룰 수 없는 경우 등)는 질문이 아니라 **상태 보고 + 세션 종료**로 처리한다: 무엇이 왜 막혔는지 `shorts-jobs/<id>/`의 보고 파일과 최종 응답에 적고, 거기서 끝낸다.
