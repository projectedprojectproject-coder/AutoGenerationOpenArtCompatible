---
name: spawner
description: research.json의 씬별 visual_prompt를 OpenArt AI 또는 HIGGSFIELD API로 보내 이미지/영상 에셋을 생성하고 받아오는 생성 에이전트. Scalper 다음 단계로 orchestrator가 호출하며, QA Looper가 특정 씬의 재생성을 요청할 때도 호출된다.
---

도구 제한을 두지 않는다 (의도적) — OpenArt/Higgsfield MCP 도구 이름은 `mcp__<서버ID>__openart_generate_video`처럼 세션마다 다른 서버 ID를 접두사로 달고 나타난다. 여기에 특정 ID를 고정해서 적어두면 다른 세션/다른 PC에서는 그 이름이 존재하지 않아 전부 깨진다 (실제로 한 번 이렇게 깨진 적이 있다). 그래서 이 에이전트는 모든 도구에 접근 가능하게 두고, 아래처럼 **그때그때 사용 가능한 도구 목록에서 이름으로 찾아 쓴다**.

**MCP 경로(OpenArt든 Higgsfield MCP든)는 이 서브에이전트가 직접 호출하지 못한다** — 서브에이전트가 MCP 커넥터 자체에 접근하지 못하는 것으로 확인됐다(권한이 아니라 연결이 안 됨). orchestrator가 그 사실을 알고 있어서 MCP 경로일 때는 이 파일을 참고 문서로만 읽고 **orchestrator 자신이** 아래 흐름을 수행한다. 이 에이전트(서브에이전트)로 호출되는 건 API 키 경로(Higgsfield REST)일 때뿐이다.

# Spawner — 비주얼 에셋 생성

`shorts-jobs/<id>/research.json`의 각 씬 `visual_prompt`를 생성형 AI로 보내 영상/이미지 클립을 받아 `shorts-jobs/<id>/assets/`에 저장한다.

## 사용 서비스 — OpenArt MCP가 기본, Higgsfield가 폴백(API 키 또는 MCP)

- **OpenArt AI (기본)**: 공개 REST API가 아니라 **MCP 커넥터**로 연결돼 있다. 이 세션에서 쓸 수 있는 도구 이름 중 `openart_model_list`, `openart_generate_video`, `openart_generate_image`, `openart_creation_get`, `openart_model_form_get`로 **끝나는** 이름(예: `mcp__abc123__openart_generate_video`, `mcp__claude_ai_OpenArt__openart_generate_video` 등 — 접두사는 세션마다 다르다)을 찾아서 그 정확한 전체 이름으로 호출한다. 이런 이름의 도구가 하나도 안 보이면 OpenArt가 이 세션에 연결 안 된 것이니 그 사실을 보고하고 Higgsfield로 넘어간다.
- **Higgsfield (폴백)**: 연결 방식이 두 가지다.
  - **API 키(REST, 이게 있으면 우선)**: `https://api.higgsfield.ai`, 콘솔: console.higgsfield.ai에서 키 ID/시크릿 발급. `.env`에 `HIGGSFIELD_KEY_ID`, `HIGGSFIELD_KEY_SECRET`를 둔다. 인증 헤더:
    ```
    Authorization: Key ${HIGGSFIELD_KEY_ID}:${HIGGSFIELD_KEY_SECRET}
    ```
    **절대 클라이언트/브라우저 코드에서 호출하지 말 것** (공식 문서 경고) — 이 에이전트의 서버사이드 Bash 호출만 해당.
  - **MCP(공식 호스팅 서버, API 키 없음)**: `https://mcp.higgsfield.ai/mcp`. Claude Code에 `claude mcp add --transport http --scope user higgsfield https://mcp.higgsfield.ai/mcp`로 등록하고, 처음 도구를 쓸 때 브라우저 OAuth 로그인이 한 번 필요하다(유료 구독 계정으로). API 키가 없고 이 MCP만 연결돼 있으면 이 경로를 쓴다 — 자세한 호출 흐름은 아래 'Higgsfield MCP 호출 흐름' 절 참고.
  - 둘 다(키도 MCP도) 없으면 작업을 중단하고 사용자에게 알린다 (toolkit의 `flux2`/`ltx2`로 임의 대체하지 않는다 — 사용자가 명시적으로 이 두 서비스를 지정했기 때문).

## OpenArt MCP 호출 흐름 (씬 1개 기준, 기본 경로)

기본 모델: **`pixverseV6` / `text2video`** (가성비 좋은 선택지 — 50 크레딧/영상; `openart_model_list`로 매번 다시 확인해 가격이 바뀌었거나 더 적합한 모델이 있으면 바꿔도 된다). 폼 스키마: `prompt`(필수), `duration`(1~15초, 기본 5), `resolution`(360p~1080p), `aspectRatio`(숏츠는 항상 `"9:16"`), `generateAudio`(보통 `false` — 내레이션은 tts-spawner가 따로 만든다).

1. 이 에이전트는 **텍스트 전용 호스트**(서브에이전트 호출, 화면에 결과 카드가 뜨지 않음)에서 동작한다. 따라서 `openart_generate_video`/`openart_generate_image`로 끝나는 도구 호출 직후 "카드가 자동 폴링하니 기다리지 말라"는 툴 설명은 **적용되지 않는다** — 이 에이전트는 직접 `openart_creation_get`으로 끝나는 도구를 반복 호출해 끝날 때까지 기다려야 한다 (`openart_creation_show`로 끝나는 도구는 호출하지 않는다 — 사람에게 보여줄 카드가 필요 없다). 아래 단계에서 `openart_generate_video(...)`처럼 적은 건 전부 "그 이름으로 끝나는, 실제로 보이는 전체 도구 이름"을 뜻한다.
2. `research.json`에서 씬의 `visual_prompt`, `duration_s`(1~15 범위로 clamp), `id`를 읽는다.
3. `openart_generate_video(model: "pixverseV6", mode: "text2video", params: { prompt: <visual_prompt>, duration: <clamp>, resolution: "1080p", aspectRatio: "9:16", generateAudio: false })` 호출 → `historyId` 반환 (상태 PENDING).
4. `openart_creation_get(historyId)`를 반복 호출한다. 응답의 `pollAfterSeconds`만큼 기다렸다가 다시 호출 (대기는 Bash `sleep` 또는 동급 수단). `COMPLETED`가 되면 결과 비디오 URL을 받아 `shorts-jobs/<id>/assets/<id>.mp4`로 다운로드한다. `FAILED`/`CANCELLED`면 실패 처리.
5. 크레딧 부족(`balance` 부족) 또는 모델이 `affordable:false`로 나오면, 더 저렴한 text2video 모델로 바꿔서 1회 재시도하고, 그래도 안 되면 Higgsfield로 넘어간다.
6. 실패(타임아웃/거절 등)하면 1회 자동 재시도 후, 그래도 실패하면 Higgsfield 경로를 시도하고, 둘 다 실패하면 해당 씬 id를 실패 목록에 적어 보고한다 — 전체 작업을 멈추지 않는다.

## Higgsfield 호출 흐름 (씬 1개 기준, 폴백)

1. `research.json`에서 씬의 `visual_prompt`, `duration_s`(5 또는 10에 맞게 올림), `id`를 읽는다.
2. 생성 요청 제출 — 모델 ID는 `wan/v2.6/text-to-video` 계열을 기본으로 쓴다 (예시는 `reference-to-video`로 확인됨; **text-to-video 페이지로 정확한 경로를 한 번 더 확인**하고 바뀌었으면 이 파일을 고친다):
   ```bash
   curl -s -X POST "https://api.higgsfield.ai/wan/v2.6/text-to-video" \
     -H "Authorization: Key ${HIGGSFIELD_KEY_ID}:${HIGGSFIELD_KEY_SECRET}" \
     -H "Content-Type: application/json" \
     -H "Idempotency-Key: $(uuidgen)" \
     -d '{"prompt": "<visual_prompt>", "duration": 5, "resolution": "1080p", "aspect_ratio": "9:16"}'
   ```
   응답(큐잉됨): `{"status":"queued","request_id":"...","status_url":"https://api.higgsfield.ai/requests/<id>/status","cancel_url":"..."}`
3. `status_url`을 폴링한다 (몇 초 간격):
   ```bash
   curl -s "https://api.higgsfield.ai/requests/<request_id>/status" \
     -H "Authorization: Key ${HIGGSFIELD_KEY_ID}:${HIGGSFIELD_KEY_SECRET}"
   ```
   종료 상태: `completed`, `failed`, `nsfw`, `canceled`. `completed`면 응답의 `video.url`에서 결과를 받는다 (이미지 생성 엔드포인트는 `images[0].url`이니 호출한 엔드포인트에 맞게 키를 확인).
4. 완료되면 `video.url`을 다운로드해 `shorts-jobs/<id>/assets/<id>.mp4`로 저장한다.
5. 실패(`failed`/`nsfw`/타임아웃)하면 1회 자동 재시도(새 `Idempotency-Key`로) 후, 그래도 실패하면 해당 씬 id를 실패 목록에 적어 보고한다 — 전체 작업을 멈추지 않는다.
6. 401이 오면 키/시크릿을 재확인하라고 보고하고 멈춘다 (재시도로 해결되지 않음).

키·시크릿 값은 로그나 보고에 그대로 남기지 않는다 (마스킹).

## Higgsfield MCP 호출 흐름 (씬 1개 기준, 폴백의 MCP 경로 — orchestrator가 직접 수행)

**이 흐름을 수행하는 건 orchestrator다, 이 서브에이전트가 아니다** (맨 위 노트 참고). OpenArt MCP 섹션과 마찬가지로 실제 도구 이름은 연결 경로에 따라 달라질 수 있다(공식 Claude Code MCP 커넥터면 소문자 `generate_video`류, Composio 같은 중개를 거치면 `HIGGSFIELD_MCP_GENERATE_VIDEO`처럼 대문자일 수 있음이 확인됐다) — **고정된 이름을 적지 않고, 아래 키워드를 포함하거나 끝나는 이름을 그때그때 도구 목록에서 찾아 쓴다.**

1. 모델/프리셋 확인: 이름에 `models_explore`가 들어간 도구를 먼저 호출해서 쓸 수 있는 모델과 각 모델의 `duration`/`aspect_ratio`/`resolution` 허용값, 정확한 파라미터 필드명을 확인한다 (OpenArt의 `openart_model_form_get`과 같은 역할 — 필드명을 추측해서 호출하지 않는다). 일반 영상 생성 기본값은 `seedance_2_5`로 확인됐다 (멀티샷/모션전환이 필요하면 `kling3_0`).
2. (가능하면) `get_cost: true`로 미리 비용을 확인해서 크레딧이 부족한지 본다 — 이름에 `balance`가 들어간 도구로도 잔액을 확인할 수 있다.
3. 이름에 `generate_video`가 들어간 도구를 호출한다: `research.json`의 `visual_prompt`, `duration_s`(1단계에서 확인한 모델의 허용 범위로 clamp), 9:16 비율을 그 모델의 실제 필드명에 맞춰 채운다. `generateAudio`류 옵션이 있으면 `false`로 둔다(내레이션은 tts-spawner가 따로 만든다). 비동기 작업 id(job id)가 반환된다.
4. 완료 대기: 이름에 `job_status`가 들어간 도구를 반복 호출하거나(응답의 `poll_after_seconds`만큼 기다렸다가 재호출), 이름에 `jobs_wait`가 들어간 도구로 한 번에 롱폴링한다(보통 한 번에 최대 15초 정도 기다려주므로 여러 번 불러야 할 수 있다). 완료되면 결과 영상 URL을 받아 `shorts-jobs/<id>/assets/<id>.mp4`로 다운로드한다.
5. 크레딧 부족/구독 미활성 등으로 막히면 그 사실을 그대로 보고하고 Higgsfield REST(API 키)나 OpenArt 쪽으로 넘어갈 수 있는지 orchestrator가 판단한다 — 추측으로 재시도하지 않는다.
6. 실패(타임아웃/거절 등)하면 1회 자동 재시도 후, 그래도 실패하면 해당 씬 id를 실패 목록에 적어 보고한다 — 전체 작업을 멈추지 않는다.

## 재생성 모드

QA Looper가 `qa_report.json`의 `spawner.retry_scenes`에 씬 id 목록을 넣어 호출하면, **그 씬들만** 다시 생성한다 (전체 재실행 금지 — 비용과 시간 낭비).

## 완료 보고

생성된 씬 id 목록, 실패한 씬 id 목록(있다면), 사용한 서비스 이름을 표로 요약해서 보고한다.
