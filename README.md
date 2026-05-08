# ★ MACH — AI Character Simulator

레트로 8비트 스타일의 AI 캐릭터 시뮬레이터입니다.  
캐릭터를 만들면 자율적으로 행동하고, 실시간으로 대화할 수 있습니다.

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| **백엔드 프레임워크** | FastAPI + Uvicorn |
| **AI (LLM)** | OpenAI API (`gpt-4o`) |
| **벡터 DB (메모리)** | Qdrant |
| **임베딩 모델** | sentence-transformers (`all-MiniLM-L6-v2`, 로컬 실행) |
| **실시간 통신** | WebSocket |
| **프론트엔드** | Vanilla HTML/CSS/JS, NES.css, Press Start 2P 폰트 |
| **데이터 검증** | Pydantic v2 |
| **환경변수 관리** | python-dotenv |

---

## 아키텍처

```
┌─────────────────────────────────────────────────────┐
│                    Browser (Frontend)                │
│  frontend/index.html                                 │
│  - 캐릭터 생성 화면 / 게임 화면                         │
│  - REST API 호출 (캐릭터 생성, 채팅)                    │
│  - WebSocket 연결 (실시간 상태 수신)                    │
└────────────────────┬────────────────────────────────┘
                     │  HTTP / WebSocket
┌────────────────────▼────────────────────────────────┐
│              FastAPI Backend (main.py)               │
│                                                      │
│  REST Endpoints:                                     │
│    POST /api/characters      캐릭터 생성              │
│    GET  /api/characters      캐릭터 목록              │
│    GET  /api/characters/{id} 캐릭터 조회              │
│    POST /api/chat            채팅                    │
│    POST /api/characters/{id}/tick  수동 틱(디버그)    │
│                                                      │
│  WebSocket:                                          │
│    WS /ws/character/{id}     실시간 상태 스트리밍      │
└───────┬──────────────────────────┬──────────────────┘
        │                          │
┌───────▼──────────┐    ┌──────────▼──────────────────┐
│   agent.py       │    │   memory.py                  │
│                  │    │                              │
│ - 자율 에이전트    │    │ - Qdrant 벡터 DB 연결        │
│   루프 (2분 주기) │    │ - 텍스트 임베딩 (로컬 모델)   │
│ - OpenAI API     │    │ - 메모리 저장/검색 (RAG)      │
│   행동 결정       │    │                              │
│ - RAG 기반 채팅   │    │  Collections:               │
│                  │    │    diary_entries (행동 일기)  │
└───────┬──────────┘    │    chat_logs (대화 기록)      │
        │               └──────────────────────────────┘
┌───────▼──────────┐
│   OpenAI API     │
│   (gpt-4o)       │
└──────────────────┘
```

### 주요 동작 흐름

**1. 자율 에이전트 루프**
```
2분마다 자동 실행
  → Qdrant에서 관련 일기 기억 검색 (RAG)
  → OpenAI에 현재 스탯 + 기억 전달
  → OpenAI가 다음 행동 결정 (SLEEPING / STUDYING / CLEANING / CHILLING)
  → 스탯 업데이트 (에너지/청결/지식/기분)
  → 행동 일기를 Qdrant에 저장
  → WebSocket으로 모든 연결된 클라이언트에게 상태 브로드캐스트
```

**2. 채팅 (RAG 기반)**
```
유저 메시지 입력
  → Qdrant에서 관련 일기/대화 기록 검색
  → 시스템 프롬프트 구성 (캐릭터 페르소나 + 현재 스탯 + 검색된 기억)
  → OpenAI에 전달 → 캐릭터 답변 생성
  → 대화 내용을 Qdrant에 저장 (다음 대화에 활용)
```

---

## 프로젝트 구조

```
mach/
├── backend/
│   ├── main.py       # FastAPI 앱, REST/WebSocket 엔드포인트
│   ├── agent.py      # OpenAI 호출, 자율 에이전트 루프, 채팅 로직
│   ├── memory.py     # Qdrant 연결, 메모리 저장/검색
│   ├── models.py     # 데이터 모델 (Character, Stats, Action 등)
│   ├── store.py      # 인메모리 캐릭터 저장소, WebSocket 매니저
│   └── config.py     # 환경변수 로드
├── frontend/
│   └── index.html    # 단일 페이지 프론트엔드 (NES.css 레트로 UI)
├── tests/
│   └── test_e2e.py   # E2E 테스트
├── requirements.txt
└── .env              # 환경변수 (직접 생성 필요)
```

### 캐릭터 스탯 시스템

| 스탯 | 설명 |
|------|------|
| **Energy** | 에너지. SLEEPING으로 회복, STUDYING/CLEANING으로 감소 |
| **Cleanliness** | 청결도. CLEANING으로 회복, 시간이 지나면 감소 |
| **Knowledge** | 지식. STUDYING으로 증가 |
| **Mood** | 스탯 조합으로 자동 결정 (HAPPY / TIRED / GRUMPY / FOCUSED / CHILL / ENERGETIC) |

---

## 실행 방법

### 사전 요구사항

- Python 3.9+
- [Qdrant](https://qdrant.tech/) — 로컬 실행 권장 (Docker)
- OpenAI API 키

### 1. Qdrant 실행 (Docker)

```bash
docker run -p 6333:6333 qdrant/qdrant
```

### 2. 환경변수 설정

프로젝트 루트에 `.env` 파일 생성:

```env
OPENAI_API_KEY=sk-...          # 필수: OpenAI API 키
OPENAI_MODEL=gpt-4o            # 선택: 기본값 gpt-4o

QDRANT_URL=http://localhost:6333  # 선택: 기본값 localhost
QDRANT_API_KEY=                   # 선택: Qdrant Cloud 사용 시만 필요

AGENT_LOOP_INTERVAL_MINUTES=2  # 선택: 자율 행동 주기 (분), 기본값 2
PORT=8000                      # 선택: 기본값 8000
```

### 3. 패키지 설치

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4. 백엔드 서버 실행

```bash
source venv/bin/activate
uvicorn backend.main:app --reload
```

서버 주소: `http://127.0.0.1:8000`  
API 문서: `http://127.0.0.1:8000/docs`

### 5. 프론트엔드 실행

별도 터미널에서:

```bash
cd frontend
python3 -m http.server 3000
```

브라우저에서 `http://localhost:3000` 접속

> 프론트엔드는 백엔드(`8000`)에 직접 API 요청을 보냅니다.  
> 백엔드가 먼저 실행되어 있어야 합니다.

### 6. 사용 방법

1. `http://localhost:3000` 접속
2. 캐릭터 이름과 페르소나(성격/배경) 입력 후 **INSERT COIN & START**
3. 게임 화면에서 캐릭터의 스탯과 현재 행동 확인
4. 채팅창에서 캐릭터와 대화
5. 2분마다 OpenAI가 스탯을 보고 다음 행동을 자동 결정하며 실시간으로 화면이 업데이트됨

---

## API 요약

| Method | Endpoint | 설명 |
|--------|----------|------|
| `POST` | `/api/characters` | 캐릭터 생성 |
| `GET` | `/api/characters` | 전체 캐릭터 목록 |
| `GET` | `/api/characters/{id}` | 특정 캐릭터 조회 |
| `POST` | `/api/chat` | 캐릭터와 채팅 |
| `POST` | `/api/characters/{id}/tick` | 수동으로 에이전트 틱 실행 (테스트용) |
| `WS` | `/ws/character/{id}` | 실시간 상태 스트리밍 |
| `GET` | `/health` | 서버 상태 확인 |

---

## 주의사항

- 캐릭터 데이터는 **인메모리**에만 저장되므로 서버 재시작 시 초기화됩니다.
- Qdrant의 대화/일기 기록은 서버 재시작 후에도 유지됩니다.
- Qdrant 없이도 서버는 실행되지만, 메모리 기능(RAG)은 동작하지 않습니다.
