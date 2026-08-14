import { Either, ParseResult, Schema } from "effect";

const FULL_SHA = /^[0-9a-f]{40}$/;
const CASE_ID = /^[a-z0-9][a-z0-9-]{2,79}$/;
const PYTEST_FILE = /^tests\/[A-Za-z_][A-Za-z0-9_]*\.py$/;

const CorpusCaseWireSchema = Schema.Struct({
  id: Schema.String,
  input: Schema.String,
  base_sha: Schema.String,
  oracle_sha: Schema.String,
  split: Schema.Literal("calibration", "validation", "heldout"),
  submission_paths: Schema.Array(Schema.String),
  verifier_paths: Schema.Array(Schema.String),
  verifier: Schema.Array(Schema.String),
  timeout_seconds: Schema.Number,
  tags: Schema.Array(Schema.String),
});

type CorpusCaseWire = typeof CorpusCaseWireSchema.Type;

export type CorpusSplit = CorpusCaseWire["split"];

export interface CorpusCase {
  readonly id: string;
  readonly input: string;
  readonly baseSha: string;
  readonly oracleSha: string;
  readonly split: CorpusSplit;
  readonly submissionPaths: readonly string[];
  readonly verifierPaths: readonly string[];
  readonly verifier: readonly string[];
  readonly timeoutSeconds: number;
  readonly tags: readonly string[];
}

export interface CorpusMetadata {
  readonly case_id: string;
  readonly base_sha: string;
  readonly oracle_sha: string;
  readonly split: CorpusSplit;
  readonly submission_paths: readonly string[];
  readonly verifier_paths: readonly string[];
  readonly verifier: readonly string[];
  readonly timeout_seconds: number;
  readonly tags: readonly string[];
}

export interface DomainFailure {
  readonly reason: string;
}

export type DomainResult<A> =
  | { readonly ok: true; readonly value: A }
  | { readonly ok: false; readonly error: DomainFailure };

const success = <A>(value: A): DomainResult<A> => ({ ok: true, value });
const failure = (reason: string): DomainResult<never> => ({
  ok: false,
  error: { reason },
});

const unicodeLength = (value: string): number => [...value].length;

const boundedString = (
  value: string,
  name: string,
  minimum: number,
  maximum: number,
): DomainResult<string> => {
  const length = unicodeLength(value);
  return minimum <= length && length <= maximum
    ? success(value)
    : failure(
        `${name} must be a string of length ${minimum} through ${maximum}`,
      );
};

const boundedStringArray = (
  values: readonly string[],
  name: string,
  minimum: number,
  maximum: number,
): DomainResult<readonly string[]> => {
  if (values.length < minimum || values.length > maximum) {
    return failure(
      `${name} must be a list with ${minimum} through ${maximum} items`,
    );
  }
  if (values.some((value) => value.length === 0)) {
    return failure(`${name} items must be non-empty strings`);
  }
  return success(Object.freeze([...values]));
};

const hasDuplicates = (values: readonly string[]): boolean =>
  new Set(values).size !== values.length;

const repositoryPathError = (
  rawPath: string,
  kind: string,
): string | undefined => {
  if (
    rawPath.startsWith("/") ||
    rawPath.includes("\\") ||
    rawPath.split("/").some((part) => part === "" || part === "." || part === "..")
  ) {
    return `${kind} path is not repository-relative: ${rawPath}`;
  }
  return undefined;
};

export const isUnittestVerifier = (verifier: readonly string[]): boolean =>
  verifier.length >= 5 &&
  (verifier[0] === "python" || verifier[0] === "python3") &&
  verifier[1] === "-m" &&
  verifier[2] === "unittest" &&
  verifier.at(-1) === "-v" &&
  verifier
    .slice(3, -1)
    .every((module) => /^tests(?:\.[A-Za-z_][A-Za-z0-9_]*)+$/.test(module));

export const isPytestVerifier = (verifier: readonly string[]): boolean =>
  verifier.length === 7 &&
  verifier[0] === "python3" &&
  verifier[1] === "-m" &&
  verifier[2] === "pytest" &&
  verifier[3] === "-vv" &&
  verifier[4] === "-p" &&
  verifier[5] === "no:cacheprovider" &&
  verifier[6] !== undefined &&
  PYTEST_FILE.test(verifier[6]);

const freezeCase = (wire: CorpusCaseWire): CorpusCase =>
  Object.freeze({
    id: wire.id,
    input: wire.input,
    baseSha: wire.base_sha,
    oracleSha: wire.oracle_sha,
    split: wire.split,
    submissionPaths: Object.freeze([...wire.submission_paths]),
    verifierPaths: Object.freeze([...wire.verifier_paths]),
    verifier: Object.freeze([...wire.verifier]),
    timeoutSeconds: wire.timeout_seconds,
    tags: Object.freeze([...wire.tags]),
  });

export const decodeCorpusCase = (value: unknown): DomainResult<CorpusCase> => {
  const decoded = Schema.decodeUnknownEither(CorpusCaseWireSchema, {
    errors: "all",
    onExcessProperty: "error",
  })(value);
  if (Either.isLeft(decoded)) {
    return failure(ParseResult.TreeFormatter.formatErrorSync(decoded.left));
  }
  const wire = decoded.right;

  const caseId = boundedString(wire.id, "id", 3, 80);
  if (!caseId.ok) return caseId;
  if (!CASE_ID.test(caseId.value)) {
    return failure("id must be lower-case hyphen syntax");
  }
  const instruction = boundedString(wire.input, "input", 32, 8_000);
  if (!instruction.ok) return instruction;
  for (const [name, sha] of [
    ["base_sha", wire.base_sha],
    ["oracle_sha", wire.oracle_sha],
  ] as const) {
    if (unicodeLength(sha) !== 40 || !FULL_SHA.test(sha)) {
      return failure(`${name} must be a full lower-case Git SHA`);
    }
  }
  if (wire.base_sha === wire.oracle_sha) {
    return failure("base_sha and oracle_sha must differ");
  }

  const submissionPaths = boundedStringArray(
    wire.submission_paths,
    "submission_paths",
    1,
    16,
  );
  if (!submissionPaths.ok) return submissionPaths;
  for (const rawPath of submissionPaths.value) {
    const reason = repositoryPathError(rawPath, "submission");
    if (reason !== undefined) return failure(reason);
  }
  if (hasDuplicates(submissionPaths.value)) {
    return failure("submission_paths contains duplicates");
  }

  const verifierPaths = boundedStringArray(
    wire.verifier_paths,
    "verifier_paths",
    1,
    16,
  );
  if (!verifierPaths.ok) return verifierPaths;
  for (const rawPath of verifierPaths.value) {
    const reason = repositoryPathError(rawPath, "verifier");
    if (reason !== undefined) return failure(reason);
    const root = rawPath.split("/", 1)[0];
    if (root !== "tests" && root !== "fixtures" && root !== "spec") {
      return failure(`verifier path is outside the admitted roots: ${rawPath}`);
    }
  }
  if (hasDuplicates(verifierPaths.value)) {
    return failure("verifier_paths contains duplicates");
  }
  const overlap = submissionPaths.value.filter((path) =>
    verifierPaths.value.includes(path),
  );
  if (overlap.length > 0) {
    return failure(`submission and verifier paths overlap: ${overlap.join(",")}`);
  }

  const verifier = boundedStringArray(wire.verifier, "verifier", 2, 32);
  if (!verifier.ok) return verifier;
  const unittest = isUnittestVerifier(verifier.value);
  const pytest = isPytestVerifier(verifier.value);
  if (!unittest && !pytest) {
    return failure(
      "verifier must be a verbose unittest module command or a closed pytest file command",
    );
  }
  if (
    pytest &&
    verifier.value[6] !== undefined &&
    !verifierPaths.value.includes(verifier.value[6])
  ) {
    return failure("pytest verifier path must be listed in verifier_paths");
  }
  if (verifier.value.some((item) => /[\u0000\r\n]/.test(item))) {
    return failure("verifier arguments must be single-line strings");
  }

  if (
    !Number.isInteger(wire.timeout_seconds) ||
    wire.timeout_seconds < 1 ||
    wire.timeout_seconds > 600
  ) {
    return failure("timeout_seconds must be an integer from 1 through 600");
  }

  const tags = boundedStringArray(wire.tags, "tags", 1, 16);
  if (!tags.ok) return tags;
  if (hasDuplicates(tags.value)) {
    return failure("tags contains duplicates");
  }
  for (const tag of tags.value) {
    if (!CASE_ID.test(tag)) {
      return failure(`tag is not lower-case hyphen syntax: ${tag}`);
    }
  }
  return success(freezeCase(wire));
};

export const corpusMetadata = (value: CorpusCase): CorpusMetadata =>
  Object.freeze({
    case_id: value.id,
    base_sha: value.baseSha,
    oracle_sha: value.oracleSha,
    split: value.split,
    submission_paths: Object.freeze([...value.submissionPaths]),
    verifier_paths: Object.freeze([...value.verifierPaths]),
    verifier: Object.freeze([...value.verifier]),
    timeout_seconds: value.timeoutSeconds,
    tags: Object.freeze([...value.tags]),
  });

class JsonScanner {
  readonly #source: string;
  #offset = 0;

  constructor(source: string) {
    this.#source = source;
  }

  scan(): void {
    this.#skipWhitespace();
    this.#value();
    this.#skipWhitespace();
    if (this.#offset !== this.#source.length) {
      this.#raise("unexpected trailing input");
    }
  }

  #value(): void {
    const next = this.#source[this.#offset];
    if (next === "{") return this.#object();
    if (next === "[") return this.#array();
    if (next === '"') {
      this.#string();
      return;
    }
    if (next === "t") return this.#literal("true");
    if (next === "f") return this.#literal("false");
    if (next === "n") return this.#literal("null");
    this.#number();
  }

  #object(): void {
    this.#consume("{");
    this.#skipWhitespace();
    if (this.#peek("}")) {
      this.#offset += 1;
      return;
    }
    const keys = new Set<string>();
    for (;;) {
      if (!this.#peek('"')) this.#raise("object key must be a string");
      const key = this.#string();
      if (keys.has(key)) this.#raise(`duplicate JSON key: ${key}`);
      keys.add(key);
      this.#skipWhitespace();
      this.#consume(":");
      this.#skipWhitespace();
      this.#value();
      this.#skipWhitespace();
      if (this.#peek("}")) {
        this.#offset += 1;
        return;
      }
      this.#consume(",");
      this.#skipWhitespace();
    }
  }

  #array(): void {
    this.#consume("[");
    this.#skipWhitespace();
    if (this.#peek("]")) {
      this.#offset += 1;
      return;
    }
    for (;;) {
      this.#value();
      this.#skipWhitespace();
      if (this.#peek("]")) {
        this.#offset += 1;
        return;
      }
      this.#consume(",");
      this.#skipWhitespace();
    }
  }

  #string(): string {
    const start = this.#offset;
    this.#consume('"');
    while (this.#offset < this.#source.length) {
      const current = this.#source[this.#offset];
      if (current === '"') {
        this.#offset += 1;
        const raw = this.#source.slice(start, this.#offset);
        const decoded: unknown = JSON.parse(raw);
        if (typeof decoded !== "string") this.#raise("invalid JSON string");
        return decoded;
      }
      if (current === "\\") {
        this.#offset += 2;
      } else {
        this.#offset += 1;
      }
    }
    this.#raise("unterminated JSON string");
  }

  #number(): void {
    const match = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(
      this.#source.slice(this.#offset),
    );
    if (match === null) this.#raise("invalid JSON value");
    this.#offset += match[0].length;
  }

  #literal(expected: string): void {
    if (!this.#source.startsWith(expected, this.#offset)) {
      this.#raise("invalid JSON literal");
    }
    this.#offset += expected.length;
  }

  #skipWhitespace(): void {
    while (/\s/.test(this.#source[this.#offset] ?? "")) this.#offset += 1;
  }

  #consume(expected: string): void {
    if (!this.#peek(expected)) this.#raise(`expected ${expected}`);
    this.#offset += expected.length;
  }

  #peek(expected: string): boolean {
    return this.#source.startsWith(expected, this.#offset);
  }

  #raise(reason: string): never {
    throw new Error(`${reason} at offset ${this.#offset}`);
  }
}

export const parseJsonRejectingDuplicateKeys = (
  source: string,
): DomainResult<unknown> => {
  try {
    new JsonScanner(source).scan();
    return success(JSON.parse(source) as unknown);
  } catch (error) {
    return failure(error instanceof Error ? error.message : "invalid JSON");
  }
};

const normalizedLines = (stdout: string, stderr: string): readonly string[] =>
  `${stdout}\n${stderr}`.split(/\r?\n/u).map((line) => line.trim());

export const unittestSignature = (
  stdout: string,
  stderr: string,
): readonly string[] => {
  const lines = normalizedLines(stdout, stderr);
  const statuses = lines.filter((line) =>
    /^test_[^\n]+ \.\.\. (?:ok|skipped .+|expected failure)$/.test(line),
  );
  const ran = lines.flatMap((line) => {
    const match = /^Ran ([1-9][0-9]*) tests? in [0-9.]+s$/.exec(line);
    return match === null ? [] : [Number(match[1])];
  });
  const terminals = lines.filter((line) => /^OK(?: \([^\n()]+\))?$/.test(line));
  if (
    ran.length !== 1 ||
    terminals.length !== 1 ||
    ran[0] !== statuses.length ||
    new Set(statuses).size !== statuses.length
  ) {
    return Object.freeze([]);
  }
  return Object.freeze([
    ...statuses,
    `Ran ${statuses.length} tests`,
    terminals[0] as string,
  ]);
};

export const pytestSignature = (
  stdout: string,
  stderr: string,
  expectedPath?: string,
): readonly string[] => {
  const lines = normalizedLines(stdout, stderr);
  const statusPattern = /^(?<path>tests\/[^\s:]+\.py)::(?<node>[^\r\n]+?) (?<status>PASSED|FAILED|SKIPPED|XFAIL|XPASS|ERROR)\s*\[\s*(?:100|[0-9]{1,2})%\]$/;
  const statuses: string[] = [];
  for (const line of lines) {
    const match = statusPattern.exec(line);
    if (match?.groups === undefined) continue;
    const path = match.groups["path"];
    const node = match.groups["node"];
    const status = match.groups["status"];
    if (
      path === undefined ||
      node === undefined ||
      status !== "PASSED" ||
      !PYTEST_FILE.test(path) ||
      (expectedPath !== undefined && path !== expectedPath)
    ) {
      return Object.freeze([]);
    }
    statuses.push(`${path}::${node} ... PASSED`);
  }
  const collected = lines.flatMap((line) => {
    const match = /^(?:collecting \.\.\. )?collected ([0-9]+) items?$/.exec(line);
    return match?.[1] === undefined ? [] : [Number(match[1])];
  });
  const passed = lines.flatMap((line) => {
    const match = /^=+\s+([1-9][0-9]*) passed(?:, [1-9][0-9]* warnings?)? in [0-9]+(?:\.[0-9]+)?s\s+=+$/.exec(
      line,
    );
    return match?.[1] === undefined ? [] : [Number(match[1])];
  });
  const sessionStarts = lines.filter((line) =>
    /^=+\s+test session starts\s+=+$/.test(line),
  );
  if (
    sessionStarts.length !== 1 ||
    collected.length !== 1 ||
    passed.length !== 1 ||
    collected[0] === undefined ||
    passed[0] === undefined ||
    collected[0] < 1 ||
    collected[0] !== passed[0] ||
    collected[0] !== statuses.length ||
    new Set(statuses).size !== statuses.length
  ) {
    return Object.freeze([]);
  }
  return Object.freeze([
    ...statuses,
    `collected ${collected[0]} items`,
    `${passed[0]} passed`,
  ]);
};

export const verifierSignature = (
  verifier: readonly string[],
  stdout: string,
  stderr: string,
): readonly string[] => {
  if (isUnittestVerifier(verifier)) return unittestSignature(stdout, stderr);
  if (isPytestVerifier(verifier)) {
    return pytestSignature(stdout, stderr, verifier[6]);
  }
  return Object.freeze([]);
};

export interface VerifierRun {
  readonly revision: string;
  readonly returnCode: number;
  readonly stdout: string;
  readonly stderr: string;
}

export interface CaseCheck {
  readonly caseId: string;
  readonly verifier: readonly string[];
  readonly baseline: VerifierRun;
  readonly admittedSolution: VerifierRun;
  readonly oracle: VerifierRun;
}

export const isValidCaseCheck = (check: CaseCheck): boolean => {
  const admitted = verifierSignature(
    check.verifier,
    check.admittedSolution.stdout,
    check.admittedSolution.stderr,
  );
  const oracle = verifierSignature(
    check.verifier,
    check.oracle.stdout,
    check.oracle.stderr,
  );
  return (
    check.baseline.returnCode !== 0 &&
    check.admittedSolution.returnCode === 0 &&
    check.oracle.returnCode === 0 &&
    admitted.length > 0 &&
    admitted.length === oracle.length &&
    admitted.every((value, index) => value === oracle[index])
  );
};
