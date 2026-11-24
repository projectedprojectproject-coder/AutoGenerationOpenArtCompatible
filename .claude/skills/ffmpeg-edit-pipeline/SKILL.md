---
name: ffmpeg-edit-pipeline
description: ffprobe/ffmpeg만으로 돌아가는 승인 기반 영상 편집 파이프라인. 여러 클립을 합쳐 편집할 때, 사용자가 "클립들 편집해줘", "영상 잘라서 합쳐줘", "편집안 만들어줘", "프리뷰 보여줘", "최종본 렌더해줘"라고 말하면 반드시 이 순서(스펙 보고 → edit.json 승인 → 720p 프리뷰 → 최종 승인 → 풀렌더)를 따를 것. 원본 파일은 절대 수정하지 않는다.
allowed-tools: Bash(ffmpeg:*), Bash(ffprobe:*)
---

# FFmpeg 승인 기반 편집 파이프라인

여러 입력 클립을 받아 하나의 결과물로 편집할 때, 중간에 두 번 사용자 승인을 받고 진행하는 고정된 5단계 워크플로우입니다. 각 단계는 이전 단계가 끝나야 시작하고, 승인 단계에서는 반드시 멈춰서 사용자 응답을 기다립니다.

## 0. 원칙

- **원본은 읽기 전용.** 입력 클립 경로에는 절대 쓰기/덮어쓰기를 하지 않는다. 모든 산출물은 `output/` 아래에만 생성한다.
- 각 단계의 결과(표, JSON, 렌더 파일 경로)를 사용자에게 보여주고, 다음 단계로 "자동으로" 넘어가지 않는다 — 승인 단계는 멈춤 지점이다.
- 중간 산출물(edit.json, preview)이 이미 있으면 처음부터 다시 만들지 말고 그 파일을 기준으로 이어간다.

## 1단계 — 클립 스펙 표로 보고

대상 클립 전부에 대해 ffprobe로 규격을 뽑아 표로 정리한다.

```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate,duration \
  -show_entries format=duration,size \
  -of default=noprint_wrappers=1 "<clip>"
```

클립마다 돌려서 아래 형태의 마크다운 표로 사용자에게 보고한다 (단위: 길이는 초, 해상도는 WxH, 프레임레이트는 반올림):

| 파일 | 길이(s) | 해상도 | FPS | 코덱 | 비고 |
|---|---|---|---|---|---|
| clip1.mp4 | 12.4 | 1920x1080 | 30 | h264 | |
| clip2.mov | 8.1 | 3840x2160 | 60 | hevc | 해상도/FPS 불일치 → 리사이즈 필요 |

해상도·FPS·코덱이 서로 다르면 "비고" 칸에 표시해서, 이후 최종 렌더에서 통일할 타겟 스펙(예: 1920x1080 30fps)을 같이 제안한다.

## 2단계 — edit.json 작성 후 승인

편집 계획을 `output/edit.json`에 아래 스키마로 작성한다. 각 클립의 트림 구간, 순서, 타겟 출력 스펙을 담는다.

```json
{
  "version": 1,
  "target": { "width": 1920, "height": 1080, "fps": 30 },
  "clips": [
    { "source": "clip1.mp4", "in": "00:00:02.0", "out": "00:00:10.0", "note": "인트로" },
    { "source": "clip2.mov", "in": "00:00:00.0", "out": "00:00:06.5", "note": "B-roll" }
  ],
  "output": {
    "preview": "output/preview_v1.mp4",
    "final": "output/final_v1.mp4"
  }
}
```

```bash
mkdir -p output
cat > output/edit.json <<'EOF'
{ ... 위 스키마 ... }
EOF
```

작성 후 `edit.json` 내용을 사용자에게 요약해서 보여주고 **명시적 승인을 받을 때까지 3단계로 넘어가지 않는다.** 수정 요청이 오면 edit.json을 고쳐서 다시 보여준다.

## 3단계 — 720p 프리뷰 렌더 (승인 후)

edit.json이 승인되면, 빠른 속도의 저해상도 프리뷰를 렌더한다. 품질보다 속도 우선.

```bash
# clips를 edit.json 순서대로 trim + concat, 720p로 축소, 빠른 preset
ffmpeg -i clip1.mp4 -ss 00:00:02.0 -to 00:00:10.0 -c:v libx264 -preset veryfast -crf 28 -an seg1.mp4
ffmpeg -i clip2.mov -ss 00:00:00.0 -to 00:00:06.5 -c:v libx264 -preset veryfast -crf 28 -an seg2.mp4
# 해상도 통일 (예: 1280x720)
ffmpeg -i seg1.mp4 -vf "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2" seg1_720.mp4
ffmpeg -i seg2.mp4 -vf "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2" seg2_720.mp4
printf "file 'seg1_720.mp4'\nfile 'seg2_720.mp4'\n" > concat_720.txt
ffmpeg -f concat -safe 0 -i concat_720.txt -c:v libx264 -preset veryfast -crf 28 output/preview_v1.mp4
```

세그먼트/concat 중간 파일은 `output/` 하위의 임시 폴더(예: `output/_work/`)에 두고, 완료 후 정리 여부는 사용자에게 맡긴다. 렌더가 끝나면 `output/preview_v1.mp4` 경로와 길이를 보고한다.

## 4단계 — 최종 승인 후 풀렌더

사용자가 프리뷰를 확인하고 최종 승인하면, 같은 edit.json을 기준으로 원본 해상도/품질로 다시 렌더한다 (세그먼트 생성 시 `-an` 제거, 오디오 포함; CRF 18-20, preset slow/medium).

```bash
ffmpeg -i clip1.mp4 -ss 00:00:02.0 -to 00:00:10.0 -c:v libx264 -preset medium -crf 18 -c:a aac -b:a 192k seg1_final.mp4
ffmpeg -i clip2.mov -ss 00:00:00.0 -to 00:00:06.5 -c:v libx264 -preset medium -crf 18 -c:a aac -b:a 192k seg2_final.mp4
ffmpeg -i seg1_final.mp4 -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" -c:a copy seg1_final_1080.mp4
ffmpeg -i seg2_final.mp4 -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" -c:a copy seg2_final_1080.mp4
printf "file 'seg1_final_1080.mp4'\nfile 'seg2_final_1080.mp4'\n" > concat_final.txt
ffmpeg -f concat -safe 0 -i concat_final.txt -c:v libx264 -preset medium -crf 18 -c:a aac -b:a 192k -movflags +faststart output/final_v1.mp4
```

`output/final_v1.mp4`가 이미 있으면 덮어쓰지 말고 `final_v2.mp4`로 올려서 이전 버전을 보존한다. 렌더 후 ffprobe로 최종 길이/해상도를 검증해서 edit.json의 의도와 맞는지 확인하고 보고한다.

## 5단계 — 원본 보호

모든 단계에서 입력 클립 경로는 조회(`ffprobe`)와 읽기 전용 입력(`ffmpeg -i`)으로만 쓰고, 쓰기 대상은 항상 `output/` 아래 새 파일이다. 사용자가 명시적으로 "원본을 덮어써도 된다"고 하지 않는 한 원본 경로를 출력 경로로 쓰지 않는다.
