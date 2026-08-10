/** flrh-ts 계층 방향 강제 — 역방향 import = error (스킬 flrh-ts §2). */
module.exports = {
  forbidden: [
    {
      name: "domain-is-pure",
      comment:
        "domain 은 domain/contracts 외 어떤 것도 import 하지 못한다 (node 내장·effect 포함).",
      severity: "error",
      from: { path: "^src/domain" },
      to: { pathNot: "^src/(domain|contracts)" },
    },
    {
      name: "contracts-only-contracts",
      comment: "contracts 는 wire 계층 — 순수 유지 (스키마 라이브러리 도입 시 명시적으로 완화).",
      severity: "error",
      from: { path: "^src/contracts" },
      to: { pathNot: "^src/contracts", dependencyTypesNot: ["type-only"] },
    },
  ],
  options: {
    doNotFollow: { path: "node_modules" },
    tsPreCompilationDeps: true,
    tsConfig: { fileName: "tsconfig.json" },
    enhancedResolveOptions: {
      extensions: [".ts", ".js"],
    },
  },
};
