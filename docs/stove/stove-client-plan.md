# STOVE 에픽세븐 PC 클라이언트 지원 개발 계획

## 1. 목적

기존 Python + ADB 기반 에픽세븐 자동화 프로그램에 STOVE 공식 PC 클라이언트 지원을 추가한다.

기존 앱플레이어 지원을 제거하거나 별도 프로그램을 만드는 것이 아니라, 동일한 자동화 로직에서 여러 실행 환경을 사용할 수 있도록 Backend를 분리한다.

최종 목표:

```text
                    ┌─ ADB Backend ──── 앱플레이어
                    │
자동화 Core ────────┤
                    │
                    └─ Win32 Backend ── STOVE PC Client
```

게임 판단 로직에서는 현재 실행 환경이 ADB인지 STOVE인지 알 필요가 없도록 한다.

---

# 2. 핵심 개발 원칙

기존 프로젝트의 다음 자산을 최대한 유지한다.

- 기존 1280×720 이미지 템플릿
- 기존 ROI
- OpenCV 이미지 인식
- OCR
- 이벤트 판단 로직
- 이동/행동 결정 알고리즘
- 사용자 데이터
- 설정 구조

STOVE 지원 때문에 기존 게임 로직을 별도로 복제하지 않는다.

---

# 3. 내부 표준 해상도

프로그램의 논리적 기준 해상도는 기존과 동일하게 유지한다.

```text
1280 × 720
```

모든 게임 판단 로직은 이 좌표계를 사용한다.

예:

```text
ROI
x = 900
y = 100
w = 200
h = 80

Click
x = 1050
y = 620
```

이 좌표들은 실행 환경과 관계없이 항상 1280×720 기준이다.

---

# 4. 전체 구조

목표 구조:

```text
                     ┌─────────────────────┐
                     │   Automation Core   │
                     │                     │
                     │ State / Event Logic │
                     │ OCR / OpenCV        │
                     │ Route Calculation   │
                     └──────────┬──────────┘
                                │
                        1280 × 720
                        Logical Space
                                │
             ┌──────────────────┴──────────────────┐
             │                                     │
      Capture Interface                      Input Interface
             │                                     │
       ┌─────┴─────┐                         ┌─────┴─────┐
       │           │                         │           │
      ADB        Win32                      ADB        Win32
       │           │                         │           │
       ↓           ↓                         ↓           ↓
  App Player   STOVE Client             App Player  STOVE Client
```

---

# 5. CaptureBackend 추상화

게임 화면을 가져오는 기능을 Backend로 분리한다.

개념:

```text
CaptureBackend

capture()
    ↓
Game Frame
```

구현:

```text
CaptureBackend
 ├─ AdbCaptureBackend
 └─ Win32CaptureBackend
```

### AdbCaptureBackend

현재 구현을 최대한 그대로 사용한다.

```text
ADB
 ↓
screencap
 ↓
image
```

### Win32CaptureBackend

PoC에서 성공한 캡처 방식을 사용한다.

후보:

```text
PrintWindow
Windows Graphics Capture / FramePool
```

PoC 결과에서 가장 안정적인 하나를 기본값으로 선정한다.

---

# 6. Game Area Detector

Win32 캡처 결과 전체가 실제 게임 영역이라고 가정하지 않는다.

다음을 구분한다.

```text
Window Area
Client Area
Game Rendering Area
```

예:

```text
┌───────────────────────────────┐
│ Windows Title Bar             │
├───────────────────────────────┤
│                               │
│        Game Rendering         │
│                               │
└───────────────────────────────┘
```

필요한 경우 Letterbox/Pillarbox 영역을 제거한다.

결과:

```text
Raw Capture
     ↓
Client Area
     ↓
Game Area
```

---

# 7. Resolution Normalizer

Game Area를 내부 표준 해상도로 변환한다.

```text
Actual Game Area
        ↓
Resolution Normalizer
        ↓
1280 × 720
```

예:

```text
1920 × 1080
     ↓
1280 × 720
```

또는:

```text
2560 × 1440
     ↓
1280 × 720
```

기존 OpenCV/OCR 로직에는 항상 1280×720 이미지만 전달한다.

---

# 8. 16:9 처리

16:9 해상도는 단순 Scale 변환을 기본으로 한다.

예:

```text
1280 × 720
1600 × 900
1920 × 1080
2560 × 1440
3840 × 2160
```

Scale:

```text
scale_x = actual_width / 1280
scale_y = actual_height / 720
```

16:9에서는 두 값이 동일해야 한다.

---

# 9. 비 16:9 처리

비 16:9 환경에서는 화면 전체를 1280×720으로 강제 변형하지 않는다.

예:

```text
2560 × 1080
3440 × 1440
1920 × 1200
```

먼저 실제 게임 영역을 확인한다.

### Case A — 게임 자체는 16:9

예:

```text
┌────────────────────────────────────┐
│ BLACK │      GAME 16:9      │ BLACK│
└────────────────────────────────────┘
```

게임 영역만 Crop한 후 1280×720으로 변환한다.

### Case B — 게임 UI 자체가 화면비에 따라 확장

별도의 Anchor 기반 보정 시스템을 사용한다.

이 경우 절대 좌표만으로 처리하지 않는다.

---

# 10. Coordinate Mapper

인식은 1280×720에서 하지만 실제 클릭은 원래 해상도에서 수행해야 한다.

따라서 양방향 좌표 변환 계층을 만든다.

```text
Logical → Physical
Physical → Logical
```

예:

```text
Logical
1280 × 720

Click
(1000, 600)

Actual
1920 × 1080

Scale = 1.5

Physical Click
(1500, 900)
```

Letterbox가 존재하면 Offset도 포함한다.

개념:

```text
physical_x = game_offset_x + logical_x × scale_x
physical_y = game_offset_y + logical_y × scale_y
```

Coordinate Mapper 외부에서는 실제 해상도 좌표를 직접 계산하지 않는다.

---

# 11. InputBackend 추상화

입력 기능 역시 분리한다.

```text
InputBackend

click(x, y)
swipe(...)
key(...)
```

구현:

```text
InputBackend
 ├─ AdbInputBackend
 └─ Win32InputBackend
```

### AdbInputBackend

현재 구현 사용:

```text
adb shell input tap
adb shell input swipe
```

### Win32InputBackend

PoC에서 성공한 입력 방식을 사용한다.

게임 로직에서는 다음과 같이 호출한다.

```text
click(1050, 620)
```

여기서 `(1050, 620)`은 항상 1280×720 논리 좌표다.

Backend 내부에서 실제 좌표로 변환한다.

---

# 12. 기존 이미지 템플릿

기존 템플릿의 기준을 유지한다.

```text
Template Resolution
1280 × 720
```

기존 이미지:

```text
assets/
templates/
```

는 원칙적으로 다시 제작하지 않는다.

STOVE 캡처를 1280×720으로 정규화한 뒤 기존 템플릿과 비교한다.

---

# 13. 템플릿 호환성 검증

다만 동일한 해상도라도 다음 차이가 발생할 수 있다.

- PC 클라이언트 렌더링 차이
- 안티앨리어싱
- 글꼴 렌더링
- UI Scale
- 색상
- 선명도

따라서 기존 주요 Template을 STOVE에서 검증한다.

우선순위:

```text
1. 핵심 화면 판별 이미지
2. 주요 버튼
3. 이벤트 화면
4. OCR 영역
5. 상태 아이콘
```

TemplateMatch 점수를 기록한다.

기존 Template이 충분히 인식된다면 그대로 사용한다.

---

# 14. STOVE 전용 Template 처리

기존 Template이 정상적으로 인식되지 않는 경우에만 STOVE 전용 Template을 추가한다.

예:

```text
templates/
 ├─ common/
 ├─ adb/
 └─ stove/
```

하지만 가능한 한:

```text
common
```

사용을 우선한다.

환경별 Template 복제는 최소화한다.

---

# 15. ROI 시스템

ROI 역시 1280×720 논리 좌표를 유지한다.

예:

```text
OCR_AREA = {
    x: 900,
    y: 120,
    w: 250,
    h: 80
}
```

실제 STOVE 해상도를 ROI 정의에 직접 저장하지 않는다.

---

# 16. Anchor 기반 보정

UI가 화면비에 따라 이동하는 영역에 대해서는 Anchor를 사용한다.

예:

```text
우측 상단 메뉴 아이콘 탐색
          ↓
Anchor 확보
          ↓
상대 위치 계산
          ↓
OCR / 클릭
```

예:

```text
Anchor
(x, y)

Target
(x + 50, y + 120)
```

절대 좌표보다 Anchor를 우선하는 영역을 단계적으로 늘릴 수 있다.

---

# 17. OCR

OCR 입력 역시 정규화 이후 이미지를 사용한다.

```text
STOVE Capture
      ↓
Game Area
      ↓
1280 × 720
      ↓
ROI Crop
      ↓
Preprocessing
      ↓
OCR
```

기존 OCR preprocessing을 우선 재사용한다.

STOVE에서 정확도가 떨어질 경우에만 별도의 threshold/upscale 설정을 검토한다.

---

# 18. Backend 선택

프로그램 시작 시 실행 환경을 선택한다.

예:

```text
실행 환경

○ 앱플레이어 (ADB)
○ STOVE 공식 PC 클라이언트
```

또는 자동 탐지를 지원한다.

예:

```text
ADB Device 발견
       ↓ YES
ADB Backend

       ↓ NO

STOVE Epic Seven Window 발견
       ↓ YES
Win32 Backend
```

초기 버전에서는 자동 탐지보다 명시적 선택을 우선한다.

---

# 19. 기존 Core 코드의 목표 상태

나쁜 구조:

```python
if stove:
    stove_click(...)
else:
    adb_click(...)
```

이 조건이 프로젝트 전체에 퍼져서는 안 된다.

목표:

```python
input.click(x, y)
```

Core는 이것만 호출한다.

실제 구현:

```text
ADB
또는
Win32
```

선택은 Backend에서 담당한다.

Capture도 동일하다.

---

# 20. 권장 모듈 구조

예:

```text
app/
│
├─ core/
│  ├─ automation/
│  ├─ recognition/
│  ├─ ocr/
│  └─ events/
│
├─ backend/
│  │
│  ├─ capture/
│  │  ├─ base.py
│  │  ├─ adb.py
│  │  └─ win32.py
│  │
│  └─ input/
│     ├─ base.py
│     ├─ adb.py
│     └─ win32.py
│
├─ display/
│  ├─ game_area.py
│  ├─ normalizer.py
│  └─ coordinate_mapper.py
│
└─ assets/
   └─ templates/
```

현재 프로젝트 구조가 이미 존재하므로 실제 적용 시 기존 구조를 분석한 뒤 최소 변경으로 맞춘다.

구조를 맞추기 위해 프로젝트 전체를 무조건 재작성하지 않는다.

---

# 21. 개발 단계

## Stage 1 — PoC 코드 이식

- [ ] HWND Finder
- [ ] Win32 Capture
- [ ] Win32 Input

PoC에서 검증된 코드만 기존 프로젝트로 이동한다.

---

## Stage 2 — Backend Interface

- [ ] CaptureBackend 정의
- [ ] InputBackend 정의
- [ ] 기존 ADB 코드 Backend화
- [ ] Win32 Backend 추가

이 단계에서는 게임 로직을 수정하지 않는다.

---

## Stage 3 — Resolution Normalization

- [ ] Game Area 추출
- [ ] 1280×720 변환
- [ ] Coordinate Mapper 구현
- [ ] 좌표 역변환 테스트

---

## Stage 4 — 기존 Template 검증

대표 화면을 선정한다.

- [ ] 메인 화면
- [ ] 전투 화면
- [ ] 이벤트 화면
- [ ] 팝업
- [ ] 주요 OCR 영역

ADB와 STOVE 결과를 비교한다.

---

## Stage 5 — 기존 자동화 단일 기능 테스트

가장 단순한 기존 자동화 기능 하나만 STOVE에서 실행한다.

전체 자동화를 한 번에 테스트하지 않는다.

성공 후 기능 범위를 단계적으로 확대한다.

---

## Stage 6 — 장시간 테스트

- [ ] 30분
- [ ] 1시간
- [ ] 수 시간

확인:

- Capture 누수
- HWND 변경
- 클릭 누락
- 창 이동
- 해상도 변경
- DPI Scaling
- 게임 재접속
- 팝업 발생

---

# 22. 회귀 테스트

STOVE 지원을 추가한 뒤 기존 ADB 기능이 깨지지 않아야 한다.

필수 테스트:

```text
ADB + 1280×720
```

기존 환경에서:

- [ ] 이미지 인식 동일
- [ ] OCR 동일
- [ ] 클릭 동일
- [ ] 이벤트 자동화 동일
- [ ] 기존 설정 호환

STOVE 지원 때문에 기존 사용자 환경이 변경되어서는 안 된다.

---

# 23. 실패 시 Rollback 원칙

각 Stage는 독립적으로 Commit한다.

예:

```text
1. win32-poc
2. backend-interface
3. adb-backend-migration
4. win32-backend
5. resolution-normalizer
6. coordinate-mapper
7. stove-template-adjustment
```

문제가 발생하면 해당 Stage만 되돌릴 수 있도록 한다.

대규모 일괄 리팩터링을 피한다.

---

# 24. 최종 목표

최종적으로 Core 입장에서는 다음 차이가 없어야 한다.

```text
ADB

capture()
 ↓
1280×720
 ↓
recognize()
 ↓
click(x,y)
```

```text
STOVE

capture()
 ↓
1280×720
 ↓
recognize()
 ↓
click(x,y)
```

Core가 보는 인터페이스:

```text
capture()
click()
swipe()
```

는 동일하다.

---

# 25. 최종 구조

```text
                      Epic Seven Automation
                               │
                               ▼
                     ┌───────────────────┐
                     │  Automation Core  │
                     │                   │
                     │ OpenCV            │
                     │ OCR               │
                     │ Event Logic       │
                     │ Route Logic       │
                     └─────────┬─────────┘
                               │
                         1280 × 720
                               │
                    ┌──────────┴──────────┐
                    │                     │
                    ▼                     ▼
              ADB Backend           Win32 Backend
                    │                     │
                    ▼                     ▼
               App Player          STOVE PC Client
```

---

# 26. 완료 기준

STOVE 지원은 다음 조건을 모두 만족하면 완료로 판정한다.

- [ ] 비활성 화면 캡처 안정
- [ ] 비활성 입력 안정
- [ ] 사용자 마우스 사용 방해 없음
- [ ] Foreground 강제 전환 없음
- [ ] 1280×720 기존 Template 대부분 재사용
- [ ] 기존 OCR 정상 동작
- [ ] 해상도 변경 대응
- [ ] 기존 ADB 기능 회귀 없음
- [ ] 장시간 자동화 안정

---

# 27. 개발 우선순위

가장 중요한 원칙:

> STOVE용 자동화 프로그램을 새로 만드는 것이 아니라 기존 자동화 Core에 새로운 입출력 Backend를 추가한다.

따라서 개발 순서는 항상 다음을 따른다.

```text
Win32 가능성 검증
        ↓
Backend 분리
        ↓
1280×720 정규화
        ↓
기존 인식 로직 재사용
        ↓
필요한 부분만 STOVE 보정
        ↓
전체 기능 확대
```

기존 코드와 이미지 자산의 재사용률을 최대화하고 STOVE 전용 분기를 최소화한다.



현재 스토브 클라이언트로 연결하면 비밀상점 옵션만 가동합니다. 다른 옵션에도 동작할수있도록 위에 문서를 기반으로 작업해주세요