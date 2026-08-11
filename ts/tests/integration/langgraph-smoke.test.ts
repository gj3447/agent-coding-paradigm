/**
 * langgraph(TS) 도입 스모크 — 2026-08-12.
 *
 * 왜 이 파일이 있나: 의존성을 package.json 에 적는 것과 그 런타임이 이 노드·이
 * tsconfig 에서 **실제로 도는 것**은 다른 사실이다. 설치만 하고 "쓸 수 있다"고
 * 적어 두면, 처음 쓰는 사람이 ESM/타입/버전 문제를 그때 만난다.
 *
 * 경계(스킬 flrh-ts §2): langgraph 는 **에이전트 워크플로 저작 도구**다.
 * - `src/domain` 은 순수하다 — langgraph 를 import 할 수 없다
 *   (`.dependency-cruiser.cjs` 의 `domain-is-pure` 가 error 로 막는다).
 * - 검사 런타임(SQCEDIT PLC 경로)과는 무관하다. 그쪽 상태 전이의 정본은
 *   `docs/decisions/EFFECT_ONLY_FSM_20260811.md` 가 정한 순수 F + Effect 이고,
 *   LLM 오케스트레이터는 결정론 요구를 만족하지 않는다.
 *
 * 이 시험은 LLM 을 부르지 않는다 — langgraph 는 그래프 런타임이고, 그 부분만
 * 여기서 심판한다. 모델 호출을 섞으면 네트워크·키·요금이 게이트에 들어온다.
 */
import { describe, expect, it } from "vitest";
import { Annotation, END, START, StateGraph } from "@langchain/langgraph";

const TraceState = Annotation.Root({
  steps: Annotation<string[]>({
    reducer: (previous, next) => previous.concat(next),
    default: () => [],
  }),
});

describe("langgraph 런타임", () => {
  it("노드 순서를 결정론으로 실행하고 reducer 로 상태를 누적한다", async () => {
    const graph = new StateGraph(TraceState)
      .addNode("plan", () => ({ steps: ["plan"] }))
      .addNode("act", () => ({ steps: ["act"] }))
      .addNode("verify", () => ({ steps: ["verify"] }))
      .addEdge(START, "plan")
      .addEdge("plan", "act")
      .addEdge("act", "verify")
      .addEdge("verify", END)
      .compile();

    const result = await graph.invoke({});

    expect(result.steps).toEqual(["plan", "act", "verify"]);
  });

  it("조건부 분기가 상태를 읽고 갈래를 고른다", async () => {
    const graph = new StateGraph(TraceState)
      .addNode("check", () => ({ steps: ["check"] }))
      .addNode("fix", () => ({ steps: ["fix"] }))
      .addNode("ship", () => ({ steps: ["ship"] }))
      .addEdge(START, "check")
      .addConditionalEdges(
        "check",
        (state: typeof TraceState.State) =>
          state.steps.includes("fix") ? "ship" : "fix",
        { fix: "fix", ship: "ship" },
      )
      .addEdge("fix", "ship")
      .addEdge("ship", END)
      .compile();

    const result = await graph.invoke({});

    // check → (fix 아직 없음) → fix → ship. 분기가 실제로 상태를 읽었다는 증거.
    expect(result.steps).toEqual(["check", "fix", "ship"]);
  });
});
