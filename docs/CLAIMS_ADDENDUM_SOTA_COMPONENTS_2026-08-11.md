# CLAIMS ADDENDUM — 부품(커널) 최첨단화 흡수 계획 (2026-08-11)

> Addendum pattern: 봉인된 거버넌스 산문(CLAIMS/README/ROADMAP/ADR)은 수정하지 않고 본 문서를 추가한다.
> 본 문서의 모든 제안은 **PROPOSED**이며 기존 클레임을 승격하지 않는다. 근거는 §7 출처의
> 실열람(2026-08-11, 병렬 리서치 4건, 소스 30여 건)이다. 산문 동의는 증거가 아니다.

## 0. 배경과 방법

CLAIMS_AND_STATUS의 정직한 자백 — F/L/R은 분리 레퍼런스만 MEASURED, H는 무측정, 통합
런타임 부재, M2-IL은 ad-hoc 캐시 — 에 대해, 각 부품을 **부품 단위 최첨단 이론** 위에
재정초하는 흡수 계획을 세운다. 방법은 GitAbsorption 캠페인 패턴의 이식: SOTA 시스템/이론을
해부 → 불변식 추출 → 게이트·반증 조건이 달린 구현 크기 슬라이스로 분해. 각 슬라이스는
착수 전 사전등록(prediction) 대상이다.

## 1. 교차 발견 — 독립 리서치 두 갈래가 같은 구조에 수렴

1. **narrow waist ≡ DBSP.** "signed delta + scalar frontier" 가설은 DBSP 이론
   (Z-set 스트림 + 전순서 시간 인덱스)과 동형이다. signed delta는 distinct-정규화된
   Z-set과 정확히 일치하고, 델타 합성에 아벨 군 구조를 요구하는 순간 증분화 정리
   `Q^Δ = D∘Q∘I`가 기계적으로 적용된다.
2. **4치 지지값의 이중 정식화 일치.** DBSP 측: 곱군 `Z[A] × Z[A]` (양의 증거, 음의 증거).
   bilattice 측: Belnap FOUR = {0,1}² — supported=(1,0), refuted=(0,1), unknown=(0,0),
   conflicted=(1,1). 두 리서치가 서로 모른 채 같은 쌍 구조에 도달했다. 4치는 발명품이
   아니라 정립된 대수의 재발견이며, 그 위 법칙(⊔ 병합, interlaced 단조성, 고정점 존재)을
   공짜로 상속받을 수 있다.
3. **값의 대수와 유도의 대수는 별개 층이다.** bilattice(값)와 세미링(provenance/유도)을
   한 대수로 합치려 하지 말 것 — 연결은 "provenance 0 여부 사영" 준동형 하나뿐
   (Grädel–Tannen dual-indeterminate 해석). 이 분리가 설계의 핵심이다.
4. **현 R 스칼라 frontier는 이론의 축소판이 아니라 정당한 특수화다.** 전순서에서
   antichain 크기 ≤ 1이므로, (C1) 단일 시퀀서 + (C2) 무피드백 단조 경로 + (C3) epoch 내
   동기 fixpoint면 스칼라로 형식적으로 닫힌다. Materialize가 상용 규모에서 검증한 경로와
   동일하다 (내부 격자, 시스템 경계 스칼라 가상시간).

## 2. L 커널 (M2 / M2-IL) 재정초

### 이론 앵커
- DBSP (Budiu–Chajed–McSherry–Ryzhyk–Tannen, VLDB 2023 / VLDB J 2025): Z-set 아벨 군,
  `I`/`D`/`z⁻¹`, 선형 연산자 `Q^Δ = Q`, join 3항식, 증분 distinct(상태형), 재귀는 중첩
  스트림 fixpoint — 세미나이브 평가가 정리로서 도출됨. 삽입/삭제가 같은 대수 경로
  (DRed류 비대칭의 원리적 제거).
- Provenance semirings (GKT PODS 2007 계보): 기본정리(준동형 교환) — trust/보안라벨은
  별도 코드가 아니라 같은 provenance의 준동형 평가. 부정은 m-semiring(폐기 노선)이 아니라
  dual-indeterminate `N[X,X̄]/(XX̄)`.
- Belnap FOUR / bilattice (Ginsberg–Fitting, Naish–Søndergaard 2013): 진리 순서(∧∨¬)와
  정보 순서(⊔ 병합)의 분리. Φ의 ⊑-단조성 → Knaster–Tarski 고정점 존재.
- Stratified vs WFS (Alice Ch.15): 층화가 부족해지는 조건은 정확히 "¬-간선 포함 재귀
  사이클" 하나. 층화 가능 프로그램에서 WFS ≡ stratified (총체성 정리).

### 슬라이스
| ID | 내용 | 게이트 | 반증 조건 |
|---|---|---|---|
| **L-B1** (하, 즉시) | 지지값을 FOUR 쌍 (s⁺,s⁻)으로 고정, 병합=⊔, ¬=성분 교환 | 16×16 전수 property: 현행 병합 ≡ ⊔ (멱등·교환·결합·⊥ 항등·⊤ 흡수), interlaced 단조성 | 현행 의미론이 법칙 위반 시 → 결함이 아니라 belief-revision(AGM) 필요 신호로 분리 |
| **IL-Z1** (중, ~300–500줄) | Z-set 코어(군 연산, I/D/z⁻¹, distinct) + 비재귀 stratum을 선형 통과·join 3항식으로. 4치는 Z[A]×Z[A] | 임의 assert/retract 시퀀스에서 `I(증분 출력) == naive 오라클`; `I∘D=id`·연쇄율·join 3항식 property | 오라클 불일치 시퀀스 1건(퍼저 탐색) 또는 적분 상태 음수 가중치 잔류 |
| **IL-Z2** (중) | stratum별 회로 체이닝, 부정 = Z-set 뺄셈 + distinct(antijoin) | 기존 M2 층화 픽스처 전체 + "하위 stratum 철회 → 상위 부정 리터럴 재점화" 연쇄 + counting-실패 케이스(다중 도출 후 부분 철회) 오라클 일치 | 부정 경계에서 도출 순서 의존 비결정성 1건 발견 시 접근 재검토 |
| **L-P2** (중) | provenance를 세미링 계층(Lin/Why/PosBool)에 자리매김, +/· 명시화, 준동형 게이트 | 기본정리 검산: 무작위 값매김 v에서 `Eval_v(prov(q,D̄)) == q(v(D))` | — (단, 완전성 리스크는 미해결: "주석 API 우회 읽기 0건" 계측 게이트를 별도 CI 불변으로 세우지 못하면 이 슬라이스는 절반 허명) |
| **L-N3** (중~상) | NNF 정규화 + dual token X̄ (X·X̄=0 몫), 4치 접속: (양 prov≠0?, 음 prov≠0?) 쌍 = FOUR. ¬-간선 SCC 상시 검출기 | model-defining 조건과 지지값 사영 일치; SCC 검출 시 명시 거부/플래그 | 플래그가 실워크로드에서 발화하면 그때 WFS 구현(층화 시 하위호환); 장기 0건이면 WFS는 YAGNI 기각 |
| IL-Z3 (상, 유예) | 증분 fixpoint(중첩 스트림, δ₀/∫) | 이행폐쇄에서 삽입 작업량 ∝ 델타 크기 계측 + 삭제 후 오라클 일치 | 삭제 시 복잡도 후퇴는 이론이 예고한 한계 — 반증 아님. 반증은 오직 오라클 불일치 |

### 경고 (실열람에서 확인된 함정)
- 증분 **distinct**가 가장 어려운 부품 — 가중치가 0을 스치는 시퀀스(+1,−1,+1)에서 출력 부호
  오류가 흔함. min/max 등 비선형 집계는 배제하고 "집계 무지원"을 게이트에 명문화.
- **층화 부정의 증분 datalog는 공개 구현 선례가 없다** (CEUR 2024 구현도 future work,
  Feldera는 SQL 경로) — IL-Z2는 부분 개척지이므로 naive 오라클 게이트 필수.
- m-semiring(monus) 노선 금지 — 항등식 실패 + 비실용 구성으로 문헌상 폐기.
- 재귀 provenance 의미론(all-tree/최소깊이/비재귀)은 자유변수 — 하나를 골라 문서화하지
  않으면 나중에 반드시 분쟁. 실용 권장: 흡수적 세미링 + 최소깊이(Soufflé 방식).
- 가중치와 명시 provenance 집합의 이중 장부 정합(|prov| == weight)을 fsck성 검사로.
- "세미링 주석 = 증분 delete 공짜"는 **거짓** (2026 이분법 논문) — 정확한 명제는
  "군(ring) 구조 = 삭제의 기계적 전파, 단 distinct/재귀 비용 별도".

## 3. R 커널 (M3) 승격

### 이론 앵커
Naiad/timely progress tracking (pointstamp, could-result-in, path summary), Materialize
가상시간(경계 스칼라화 선례), 동기 언어의 synchronous hypothesis(틱 원자성 = 불변 4의
정식 조상), TC39 Signals push-then-pull(값 glitch-freedom — 단 effect엔 미적용),
Reactive Streams demand 계약, Kafka pull 설계 논거.

### 슬라이스
| ID | 내용 | 게이트 | 반증 조건 |
|---|---|---|---|
| **R-S1** (소, 선행) | 스칼라 충분성 조건 C1·C2·C3을 R 불변으로 명문화 + 가드 2개: 토폴로지 등록 시 피드백 간선 정적 거부, "antichain 크기 == 1" canary assertion | 불변 3종 property + 피드백 등록 시도 → 정적 거부 negative test | C1~C3 유지 불가능한 기능 요구 실증 시 "스칼라 영구" 기각, R-S3 트리거 발동 |
| **R-S2** (중, 본명) | L→R 델타에 아벨 군 구조를 요구 스펙으로; reject-new를 coalescing mailbox(유계 버퍼가 미소비 델타를 군 덧셈으로 합산)로 대체·병행 | 군 법칙 property + **coalesce-후-적용 ≡ 개별-적용 등가성**(무손실 백프레셔의 정확성 증명) + reject-new 대비 지연/드롭률 실측 | 가역·병합 불가 델타가 L에서 발견되면 별도 effect 채널로 격리 — "모든 L→R이 한 waist를 지난다" 강가설 약화 |
| **R-S3** (문서만, 구현 유예) | 부분순서 frontier 도입 트리거 명세: T1 시퀀서 불가능/비용 초과(입력 다수는 트리거 아님), T2 비동기 fixpoint(iteration이 epoch 탈출 — 최개연), T3 R 노드 간 사이클, T4 경로별 진행 요구 | 신기능 설계 시 T1~T4 체크리스트 의무화 | "영원히 발동 안 함"은 반증 불가 명제이므로 게이트로 삼지 않음 |

### 경고
- 부분순서 progress tracking은 timely 최난 부품(기계검증 논문이 나올 정도) — "미리 구현"이
  최악의 수. Materialize도 안 했다.
- Signals의 glitch-freedom은 **값**에만 적용 — "effect는 stable frontier 확정 이후에만
  스케줄"을 별도 불변으로 못박아야 불변 4가 effect까지 확장된다.
- 원소 단위 크레딧(Reactive Streams)은 저빈도·배치 소비에 과잉 — "발행 ≤ 요청"의
  whole-batch 형태만 유지.
- C3은 epoch 내 수렴 전제 — iteration budget과 미수렴 시 epoch 실패 의미론을 정의하지
  않으면 스칼라 충분성에 구멍.
- 시퀀서는 스칼라의 대가(직렬화 병목) — 스칼라 유지 비용 > 부분순서 도입 비용이 되는
  시점(T1)은 실측으로만 판정.

## 4. H 커널 (M4B) — 유일 무측정 커널의 측정 계획

### 이론 앵커
- **결정론적 재생의 조작적 정의 = trace equality**: 재생 시 코드가 재생성한 명령 시퀀스를
  이벤트 히스토리와 대조, 불일치 즉시 정지 (Temporal/Azure/Restate 공통 커널).
- 모든 비순수 연산은 기록된 결과 경유(저널 + 메모이제이션); await 지점 = 결정 지점;
  **Azure는 JS 오케스트레이터에 async 금지·동기 generator 강제** ("Node는 async 함수의
  결정론을 보장하지 않는다") — TS 구현 직결 판례. 금지 목록(시계/랜덤/직접 I/O/환경변수/
  스레딩/전역 가변)을 ESLint 룰로 이식.
- **exactly-once의 정직한 경계**: delivery는 불가능(Two Generals), 성립하는 것은
  "저널 커밋의 exactly-once" + "멱등키·트랜잭션 3조건 하의 effectively-once processing".
  외부 효과는 계약에 exactly-once/at-least-once/at-most-once **등급 필드 필수화**.
  timeout ≠ 실패 — in-doubt를 "실패로 보고 재실행"이 중복 mutation의 근원.
- **검증은 DST** (FoundationDB/TigerBeetle VOPR/Antithesis): 단일 스레드 sans-io 커널 +
  가짜 시계 + 시드 PRNG → 시드+커밋 해시가 완전 재현 티켓. linearizability 체커는
  단일 노드 런타임에 과잉(NP-complete; 저널이 이미 전순서 = 사양).
- 오라클 5종: P1 재생 결정론(저널 byte-identical), P2 재개 등가성(임의 지점 crash+resume
  ≡ 무중단), P3 효과 정합(멱등키별 적용 ≤1, receipt 존재 시 ==1), P4 terminal 건전성
  (terminal ⇒ 전 outbox 확정, terminal 후 append 0), P5 liveness(결함 중단 후 유한 스텝
  내 terminal).

### 슬라이스
| ID | 내용 | 게이트 | 반증/음성 오라클 |
|---|---|---|---|
| **H-D1** | sans-io 순수 상태기계 커널 + SimEnv v0(가상시계·시드 PRNG·인메모리 저장소·커널 소유 스케줄러) + 이벤트 저널·재생 루프 | G1: 시드 10⁴ × 동일 시드 2회 저널 byte-identical. G2: 시드 10⁴ × append 경계 전 지점 crash+resume ≡ 무중단 | G3(음성): `Math.random()` 분기 주입 변이체에서 G1 필패 — 통과 시 하네스 vacuous |
| **H-D2** | 아웃박스 릴레이 + 멱등 재적용 + 영수증을 SimEnv 연결; mock 외부 세계가 (멱등키→적용횟수) 원장 유지; 시드가 crash 지점 선택(저널/효과/영수증/CAS 전후) | G4: 시드 10⁵ crash 스케줄에서 중복 mutation 0. G5: 거짓 terminal 0. G6: liveness | G7(음성): 영수증 기록을 효과 실행 앞으로 옮긴 변이체·멱등키 검사 제거 변이체에서 G4 필패 |
| **H-D3** | 좀비 writer(이중 재개) + in-doubt 심술(성공했지만 timeout 응답 등); CAS + epoch/세대 토큰 fencing (Restate epoch fencing 이식) | G8: 시드 10⁴ 이중-재개에서 구 epoch 저널 오염 0. G9: in-doubt에 명시 판정 경로(멱등 재시도/read-verify/등급 선언) 강제 | "그냥 재실행" 경로의 존재 자체가 반증 |

영수증 어휘에 `seed`, `git_sha`, `schedule_digest` 3필드 추가 — 시드가 곧 재현 티켓.

### 경고 (재생 결정론이 깨지는 빈도순 전형)
숨은 `Date.now()`(서드파티 내부 포함) > `Math.random()`/UUID(결정론적 Type-5로 대체) >
**Promise 인터리빙**(도착 순서가 아니라 저널 기록 순서로 소비) > 객체 키 순서 직렬화
(정렬-키 canonical JSON으로 저널 기록) > 환경변수/전역 캐시 > **코드 배포 자체**(v0 정책:
저널에 커널 버전 기록 + 불일치 시 재생 거부 명시). DST 통과는 mock이 표현하는 세계에
대해서만 유효 — mock 심술(성공-but-timeout, 재시도 시 다른 에러) 없는 커버리지는 환상.

## 5. F 커널 — 현상 유지 + 정준 인코딩 공유

F(결정론 리듀서 + inert proposal)는 이미 SOTA 정합. 남은 것은 정준 인코딩(정렬 키
canonical JSON)의 **교차 언어 골든 바이트 게이트** 하나 — H의 저널 다이제스트,
lakatotree-ts의 sha 패리티와 같은 기질이므로 세 소비처가 하나의 정본
(`spec/canonicalization.v1.json`)을 공유해야 한다.

## 6. 우선순위 제안 (PROPOSED)

1. **H-D1 → H-D2**: 유일 무측정 커널이 간판 문장 아래 있다. DST 하네스는 falsifier
   "H cannot prevent duplicate mutation or false terminal across crash/resume"의 직접 측정.
2. **IL-Z1**: M2-IL ad-hoc 캐시의 재정초 — 이론이 작아(방정식 6개) 비용 대비 최대 이득.
3. **R-S2**: waist의 대수 승격 — L(IL-Z1)과 같은 Z-set 기질을 공유하므로 순서 결합.
4. **L-B1**: 반나절짜리 검산으로 고정점 존재·병합 법칙을 공짜 상속.
5. R-S1/R-S3, L-P2/L-N3, IL-Z2/Z3, H-D3: 위 결과에 따라 사전등록 후 순차.

각 슬라이스는 착수 전 lakatotree에 prediction 사전등록을 권장 — 이 계획 자체가
에이전트 코딩 패러다임의 첫 자기적용 효능 측정 기회다.

## 7. 출처 (실열람 위주, 발췌)

DBSP/증분: Budiu et al. PVLDB 16(7) 2023 + VLDB J 2025; Feldera (github.com/feldera);
de Lima et al. Datalog 2.0 / CEUR-3801 2024; Motik et al. AAAI 2018; McSherry et al.
CIDR 2013; salsa / Adapton PLDI 2014.
Provenance/논리: Karvounarakis–Green SIGMOD Rec 41(3) 2012; Green–Karvounarakis–Tannen
PODS 2007; Grädel–Tannen arXiv:2412.07986; Bourgaux et al. KR 2022; Abiteboul–Hull–Vianu
*Foundations of Databases* Ch.15; Naish–Søndergaard TPLP 2013; Fitting JLP 1991;
Chmielewski et al. arXiv:2606.07795 (2026).
Durable/DST: Temporal Docs (workflow-definition, patching); Azure Durable Functions code
constraints (2026-02); Restate "First Principles" 2025-02; Vanlightly "Durable Function
Tree" 2025-12; TigerBeetle VOPR docs; Antithesis DST docs; Eaton 2024-08; Dudycz
(event-driven.io) outbox/delivery; Tornow (Resonate) DST 2024-03; Durable Promise Spec.
Reactive/frontier: timely dataflow book ch.5.2; McSherry 2014 (time summaries); Reactive
Streams JVM 1.0.4; TC39 Signals proposal; Materialize virtual-time/isolation docs; Kafka
4.0 design; Murray et al. SOSP 2013; Brun et al. ITP 2021; Halbwachs 1993.
