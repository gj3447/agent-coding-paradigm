import parser from "@typescript-eslint/parser";

/**
 * flrh-ts 금지 API — domain 순수성을 문법 수준에서 차단 (스킬 flrh-ts §2·§4).
 * 규칙은 전부 ESLint 코어(no-restricted-*)라 타입 정보가 필요 없고, TS 파싱만
 * @typescript-eslint/parser(TS6 API)로 한다. tsc 는 TS7 네이티브(typescript7 별칭).
 */

const tsFiles = (files, rules) => ({
  files,
  languageOptions: { parser, ecmaVersion: "latest", sourceType: "module" },
  rules,
});

export default [
  { ignores: ["node_modules/**", "dist/**"] },
  tsFiles(["src/**/*.ts", "tests/**/*.ts"], {}),
  tsFiles(["src/**/*.ts"], {
    "no-restricted-syntax": [
      "error",
      {
        selector: "MemberExpression[object.name='Effect'][property.name=/^run(Promise|Sync|Fork)/]",
        message: "Effect 실행은 entrypoints/ 와 테스트에서만.",
      },
    ],
  }),
  tsFiles(["src/domain/**/*.ts"], {
    "no-restricted-imports": [
      "error",
      {
        paths: [
          { name: "effect", message: "domain 은 순수 TS. Effect 는 application/adapters 에서." },
        ],
        patterns: [
          { group: ["effect/*"], message: "domain 은 순수 TS." },
          { group: ["node:*"], message: "domain 은 ambient 모듈 금지 — I/O 는 상위 계층 소관." },
        ],
      },
    ],
    "no-restricted-globals": [
      "error",
      { name: "Date", message: "domain 은 시간 접근 금지 — 시각은 AcceptedEvent 로 들어온다." },
      { name: "fetch", message: "domain 은 I/O 금지." },
      { name: "process", message: "domain 은 환경 접근 금지." },
      { name: "crypto", message: "domain 은 랜덤 금지 — 난수는 이벤트 데이터로." },
    ],
    "no-restricted-properties": [
      "error",
      { object: "Math", property: "random", message: "domain 은 랜덤 금지." },
    ],
    "no-restricted-syntax": [
      "error",
      { selector: "ThrowStatement", message: "domain 은 throw 금지 — rejection union 반환." },
      { selector: "AwaitExpression", message: "domain 은 async 금지 — Data → pure fn → Data." },
      { selector: "FunctionDeclaration[async=true]", message: "domain 은 async 금지." },
      { selector: "ArrowFunctionExpression[async=true]", message: "domain 은 async 금지." },
      {
        selector: "MemberExpression[object.name='Effect'][property.name=/^run(Promise|Sync|Fork)/]",
        message: "Effect 실행은 entrypoints/ 와 테스트에서만.",
      },
    ],
    "no-eval": "error",
    "no-implied-eval": "error",
    "no-new-func": "error",
  }),
  tsFiles(["src/contracts/**/*.ts"], {
    "no-restricted-imports": [
      "error",
      {
        paths: [{ name: "effect", message: "contracts 는 wire 계층 — Effect 무관." }],
        patterns: [
          { group: ["node:*"], message: "contracts 는 ambient 모듈 금지 (순수 sha256 사용)." },
        ],
      },
    ],
    "no-eval": "error",
    "no-implied-eval": "error",
    "no-new-func": "error",
  }),
];
