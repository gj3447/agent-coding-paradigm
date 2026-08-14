import { Either, ParseResult, Schema } from "effect";

const FULL_SHA = /^[0-9a-f]{40}$/;
const CASE_ID = /^[a-z0-9][a-z0-9-]{2,79}$/;
const PYTEST_FILE = /^tests\/[A-Za-z_][A-Za-z0-9_]*\.py$/;
const VERIFIER_OUTPUT_LIMIT_BYTES = 64 * 1024;
const REPOSITORY_PATH_LIMIT_BYTES = 4 * 1024;
const TEXT_ENCODER = new TextEncoder();

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

const CorpusMetadataWireSchema = Schema.Struct({
  case_id: Schema.String,
  base_sha: Schema.String,
  oracle_sha: Schema.String,
  split: Schema.Literal("calibration", "validation", "heldout"),
  submission_paths: Schema.Array(Schema.String),
  verifier_paths: Schema.Array(Schema.String),
  verifier: Schema.Array(Schema.String),
  timeout_seconds: Schema.Number,
  tags: Schema.Array(Schema.String),
});

const CompletedVerifierObservationSchema = Schema.Struct({
  kind: Schema.Literal("completed"),
  returncode: Schema.Number,
  stdout: Schema.String,
  stderr: Schema.String,
});

const ExecutionErrorObservationSchema = Schema.Struct({
  kind: Schema.Literal("execution_error"),
  error: Schema.String,
});

const VerifierObservationSchema = Schema.Union(
  CompletedVerifierObservationSchema,
  ExecutionErrorObservationSchema,
);

const BridgeRequestSchema = Schema.Union(
  Schema.Struct({
    schema_version: Schema.Literal("coding-corpus-bridge-request/v1"),
    operation: Schema.Literal("catalog"),
    corpus: Schema.String,
  }),
  Schema.Struct({
    schema_version: Schema.Literal("coding-corpus-bridge-request/v1"),
    operation: Schema.Literal("validate"),
    corpus: Schema.String,
    repository: Schema.String,
  }),
  Schema.Struct({
    schema_version: Schema.Literal("coding-corpus-bridge-request/v1"),
    operation: Schema.Literal("admit"),
    corpus: Schema.String,
    repository: Schema.String,
    python_executable: Schema.String,
  }),
  Schema.Struct({
    schema_version: Schema.Literal("coding-corpus-bridge-request/v1"),
    operation: Schema.Literal("prepare"),
    corpus: Schema.String,
    repository: Schema.String,
    python_executable: Schema.String,
    archive_directory: Schema.String,
    split: Schema.Literal("calibration", "validation", "heldout"),
  }),
  Schema.Struct({
    schema_version: Schema.Literal("coding-corpus-bridge-request/v1"),
    operation: Schema.Literal("score"),
    corpus: Schema.String,
    case_id: Schema.String,
    metadata: Schema.Unknown,
    oracle: VerifierObservationSchema,
    candidate: VerifierObservationSchema,
  }),
);

type CorpusCaseWire = typeof CorpusCaseWireSchema.Type;
type CorpusMetadataWire = typeof CorpusMetadataWireSchema.Type;

export type VerifierObservation =
  | {
      readonly kind: "completed";
      readonly returncode: number;
      readonly stdout: string;
      readonly stderr: string;
    }
  | { readonly kind: "execution_error"; readonly error: string };

export type BridgeRequest =
  | {
      readonly schema_version: "coding-corpus-bridge-request/v1";
      readonly operation: "catalog";
      readonly corpus: string;
    }
  | {
      readonly schema_version: "coding-corpus-bridge-request/v1";
      readonly operation: "validate";
      readonly corpus: string;
      readonly repository: string;
    }
  | {
      readonly schema_version: "coding-corpus-bridge-request/v1";
      readonly operation: "admit";
      readonly corpus: string;
      readonly repository: string;
      readonly python_executable: string;
    }
  | {
      readonly schema_version: "coding-corpus-bridge-request/v1";
      readonly operation: "prepare";
      readonly corpus: string;
      readonly repository: string;
      readonly python_executable: string;
      readonly archive_directory: string;
      readonly split: CorpusSplit;
    }
  | {
      readonly schema_version: "coding-corpus-bridge-request/v1";
      readonly operation: "score";
      readonly corpus: string;
      readonly case_id: string;
      readonly metadata: unknown;
      readonly oracle: VerifierObservation;
      readonly candidate: VerifierObservation;
    };

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
    /[\u0000\r\n]/u.test(rawPath) ||
    TEXT_ENCODER.encode(rawPath).byteLength > REPOSITORY_PATH_LIMIT_BYTES ||
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

export const verifierEntryPaths = (
  verifier: readonly string[],
): readonly string[] => {
  if (isUnittestVerifier(verifier)) {
    return Object.freeze(
      verifier.slice(3, -1).map((module) => `${module.replaceAll(".", "/")}.py`),
    );
  }
  return isPytestVerifier(verifier) && verifier[6] !== undefined
    ? Object.freeze([verifier[6]])
    : Object.freeze([]);
};

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
  if (
    verifier.value.some(
      (argument) => TEXT_ENCODER.encode(argument).byteLength > REPOSITORY_PATH_LIMIT_BYTES,
    )
  ) {
    return failure("verifier arguments exceed the protocol item limit");
  }
  const unittest = isUnittestVerifier(verifier.value);
  const pytest = isPytestVerifier(verifier.value);
  if (!unittest && !pytest) {
    return failure(
      "verifier must be a verbose unittest module command or a closed pytest file command",
    );
  }
  const entryPaths = verifierEntryPaths(verifier.value);
  if (entryPaths.some((path) => !verifierPaths.value.includes(path))) {
    return failure("verifier command paths must be listed in verifier_paths");
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

export const corpusCaseWire = (value: CorpusCase): CorpusCaseWire => ({
  id: value.id,
  input: value.input,
  base_sha: value.baseSha,
  oracle_sha: value.oracleSha,
  split: value.split,
  submission_paths: [...value.submissionPaths],
  verifier_paths: [...value.verifierPaths],
  verifier: [...value.verifier],
  timeout_seconds: value.timeoutSeconds,
  tags: [...value.tags],
});

const isBoundedProtocolString = (
  value: string,
  maximum: number,
): boolean =>
  value.length > 0 &&
  value.length <= maximum &&
  !/[\u0000\r\n]/u.test(value);

const validateObservation = (
  observation: VerifierObservation,
): DomainResult<VerifierObservation> => {
  if (observation.kind === "execution_error") {
    return isBoundedProtocolString(observation.error, 128)
      ? success(Object.freeze({ ...observation }))
      : failure("execution error must be a bounded single-line string");
  }
  if (
    !Number.isInteger(observation.returncode) ||
    observation.returncode < -255 ||
    observation.returncode > 255
  ) {
    return failure("verifier returncode must be an integer from -255 through 255");
  }
  const outputBytes =
    TEXT_ENCODER.encode(observation.stdout).byteLength +
    TEXT_ENCODER.encode(observation.stderr).byteLength;
  if (outputBytes > VERIFIER_OUTPUT_LIMIT_BYTES) {
    return failure("verifier output exceeds the protocol limit");
  }
  return success(Object.freeze({ ...observation }));
};

export const decodeBridgeRequest = (
  value: unknown,
): DomainResult<BridgeRequest> => {
  const decoded = Schema.decodeUnknownEither(BridgeRequestSchema, {
    errors: "all",
    onExcessProperty: "error",
  })(value);
  if (Either.isLeft(decoded)) {
    return failure(ParseResult.TreeFormatter.formatErrorSync(decoded.left));
  }
  const request = decoded.right as BridgeRequest;
  const paths = [request.corpus];
  if (request.operation === "validate" || request.operation === "admit" || request.operation === "prepare") {
    paths.push(request.repository);
  }
  if (request.operation === "admit" || request.operation === "prepare") {
    paths.push(request.python_executable);
  }
  if (request.operation === "prepare") paths.push(request.archive_directory);
  if (paths.some((path) => !isBoundedProtocolString(path, 4_096))) {
    return failure("protocol paths must be bounded single-line strings");
  }
  if (request.operation !== "score") return success(Object.freeze(request));
  if (!CASE_ID.test(request.case_id)) {
    return failure("score case_id must use lower-case hyphen syntax");
  }
  const oracle = validateObservation(request.oracle);
  if (!oracle.ok) return oracle;
  const candidate = validateObservation(request.candidate);
  if (!candidate.ok) return candidate;
  return success(
    Object.freeze({ ...request, oracle: oracle.value, candidate: candidate.value }),
  );
};

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

export type CandidateScoreDecision =
  | {
      readonly kind: "scored";
      readonly correct: boolean;
      readonly explanation: string;
      readonly returncode: number | null;
      readonly oracle_signature_match: boolean;
      readonly execution_error?: string;
    }
  | { readonly kind: "harness_error"; readonly reason: string };

const metadataMatchesCase = (value: unknown, expected: CorpusCase): boolean => {
  const decoded = Schema.decodeUnknownEither(CorpusMetadataWireSchema, {
    errors: "all",
    onExcessProperty: "error",
  })(value);
  if (Either.isLeft(decoded)) return false;
  const metadata: CorpusMetadataWire = decoded.right;
  const canonical = corpusMetadata(expected);
  return (
    metadata.case_id === canonical.case_id &&
    metadata.base_sha === canonical.base_sha &&
    metadata.oracle_sha === canonical.oracle_sha &&
    metadata.split === canonical.split &&
    metadata.timeout_seconds === canonical.timeout_seconds &&
    metadata.submission_paths.length === canonical.submission_paths.length &&
    metadata.submission_paths.every(
      (entry, index) => entry === canonical.submission_paths[index],
    ) &&
    metadata.verifier_paths.length === canonical.verifier_paths.length &&
    metadata.verifier_paths.every(
      (entry, index) => entry === canonical.verifier_paths[index],
    ) &&
    metadata.verifier.length === canonical.verifier.length &&
    metadata.verifier.every(
      (entry, index) => entry === canonical.verifier[index],
    ) &&
    metadata.tags.length === canonical.tags.length &&
    metadata.tags.every((entry, index) => entry === canonical.tags[index])
  );
};

const sameSignature = (
  left: readonly string[],
  right: readonly string[],
): boolean =>
  left.length === right.length &&
  left.every((value, index) => value === right[index]);

export const evaluateCandidateScore = (
  value: CorpusCase,
  metadata: unknown,
  oracle: VerifierObservation,
  candidate: VerifierObservation,
): CandidateScoreDecision => {
  if (!metadataMatchesCase(metadata, value)) {
    return Object.freeze({
      kind: "scored",
      correct: false,
      explanation: "sample metadata is not corpus-bound",
      returncode: null,
      oracle_signature_match: false,
    });
  }
  if (oracle.kind === "execution_error") {
    return Object.freeze({
      kind: "harness_error",
      reason: `oracle verifier could not complete: ${oracle.error}`,
    });
  }
  const oracleSignature = verifierSignature(
    value.verifier,
    oracle.stdout,
    oracle.stderr,
  );
  if (oracle.returncode !== 0 || oracleSignature.length === 0) {
    return Object.freeze({
      kind: "harness_error",
      reason: "oracle verifier did not produce a successful admitted signature",
    });
  }
  if (candidate.kind === "execution_error") {
    return Object.freeze({
      kind: "scored",
      correct: false,
      explanation: `candidate verifier could not complete: ${candidate.error}`,
      returncode: null,
      oracle_signature_match: false,
      execution_error: candidate.error,
    });
  }
  const candidateSignature = verifierSignature(
    value.verifier,
    candidate.stdout,
    candidate.stderr,
  );
  const signaturesMatch = sameSignature(candidateSignature, oracleSignature);
  const correct = candidate.returncode === 0 && signaturesMatch;
  return Object.freeze({
    kind: "scored",
    correct,
    explanation:
      `verifier exit=${candidate.returncode}; ` +
      `oracle_signature_match=${signaturesMatch}\n` +
      `stdout:\n${candidate.stdout.slice(-4_000)}\n` +
      `stderr:\n${candidate.stderr.slice(-4_000)}`,
    returncode: candidate.returncode,
    oracle_signature_match: signaturesMatch,
  });
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
