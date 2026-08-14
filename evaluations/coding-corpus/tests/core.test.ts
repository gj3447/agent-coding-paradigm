import assert from "node:assert/strict";
import test from "node:test";

import { Effect, Either } from "effect";

import { loadCases } from "../src/corpus.js";
import {
  decodeBridgeRequest,
  decodeCorpusCase,
  evaluateCandidateScore,
  isValidCaseCheck,
  parseJsonRejectingDuplicateKeys,
  pytestSignature,
  unittestSignature,
  verifierSignature,
} from "../src/domain.js";
import { FileStore, type FileStoreService } from "../src/ports.js";

const validWire = () => ({
  id: "example-case",
  input: "Repair the deterministic example while preserving its public behavior.",
  base_sha: "1".repeat(40),
  oracle_sha: "2".repeat(40),
  split: "calibration",
  submission_paths: ["src/example.py"],
  verifier_paths: ["tests/test_example.py"],
  verifier: ["python3", "-m", "unittest", "tests.test_example", "-v"],
  timeout_seconds: 60,
  tags: ["example"],
});

test("strict case decoding admits the closed unittest and pytest forms", () => {
  const unittest = decodeCorpusCase(validWire());
  assert.equal(unittest.ok, true);
  if (!unittest.ok) return;
  assert.equal(Object.isFrozen(unittest.value), true);
  assert.equal(Object.isFrozen(unittest.value.verifier), true);

  const pytestWire = {
    ...validWire(),
    verifier: [
      "python3",
      "-m",
      "pytest",
      "-vv",
      "-p",
      "no:cacheprovider",
      "tests/test_example.py",
    ],
  };
  const pytest = decodeCorpusCase(pytestWire);
  assert.equal(pytest.ok, true);
});

test("case decoding rejects excess keys, path escape, and arbitrary commands", () => {
  const excess = decodeCorpusCase({ ...validWire(), receipt_digest: "invented" });
  assert.equal(excess.ok, false);

  const escaped = decodeCorpusCase({
    ...validWire(),
    verifier_paths: ["../tests/test_example.py"],
  });
  assert.equal(escaped.ok, false);
  if (!escaped.ok) assert.match(escaped.error.reason, /repository-relative/u);

  for (const invalidPath of ["tests/test_example.py\u0000tail", "tests/test_example.py\nnext"]) {
    const invalid = decodeCorpusCase({
      ...validWire(),
      verifier_paths: [invalidPath],
    });
    assert.equal(invalid.ok, false);
    if (!invalid.ok) assert.match(invalid.error.reason, /repository-relative/u);
  }

  const command = decodeCorpusCase({
    ...validWire(),
    verifier: ["python3", "-c", "print('OK')"],
  });
  assert.equal(command.ok, false);
  if (!command.ok) assert.match(command.error.reason, /verbose unittest/u);
});

test("duplicate JSON keys fail at every object depth", () => {
  const top = parseJsonRejectingDuplicateKeys('{"id":"a","id":"b"}');
  assert.equal(top.ok, false);
  if (!top.ok) assert.match(top.error.reason, /duplicate JSON key: id/u);

  const nested = parseJsonRejectingDuplicateKeys(
    '{"outer":{"value":1,"value":2}}',
  );
  assert.equal(nested.ok, false);
  if (!nested.ok) assert.match(nested.error.reason, /duplicate JSON key: value/u);

  const valid = parseJsonRejectingDuplicateKeys(
    '{"outer":{"value":"escaped \\" quote"},"list":[1,true,null]}',
  );
  assert.equal(valid.ok, true);
});

test("Effect loader is lazy, rejects duplicate ids, and returns immutable cases", async () => {
  const line = JSON.stringify(validWire());
  let reads = 0;
  const files: FileStoreService = {
    readText: () =>
      Effect.sync(() => {
        reads += 1;
        return `${line}\n`;
      }),
    writeBytes: () => Effect.die("unused"),
    writeBytesWithinRoot: () => Effect.die("unused"),
    writeBytesAtomic: () => Effect.die("unused"),
    makeDirectory: () => Effect.die("unused"),
    makeTempDirectory: () => Effect.die("unused"),
    remove: () => Effect.die("unused"),
  };
  const program = loadCases("fixture.jsonl").pipe(
    Effect.provideService(FileStore, files),
  );
  assert.equal(reads, 0);
  const cases = await Effect.runPromise(program);
  assert.equal(reads, 1);
  assert.equal(cases.length, 1);
  assert.equal(Object.isFrozen(cases), true);

  const duplicateFiles: FileStoreService = {
    ...files,
    readText: () => Effect.succeed(`${line}\n${line}\n`),
  };
  const duplicate = await Effect.runPromise(
    loadCases("duplicate.jsonl").pipe(
      Effect.provideService(FileStore, duplicateFiles),
      Effect.either,
    ),
  );
  assert.equal(Either.isLeft(duplicate), true);
  if (Either.isLeft(duplicate)) assert.match(duplicate.left.reason, /duplicate id/u);
});

test("unittest signature requires one positive internally consistent run", () => {
  const oracle = [
    "test_example (tests.Example.test_example) ... ok",
    "Ran 1 test in 0.01s",
    "OK",
    "",
  ].join("\n");
  const equivalent = oracle.replace("0.01s", "8.75s");
  const verifier = [
    "python3",
    "-m",
    "unittest",
    "tests.test_example",
    "-v",
  ];
  assert.deepEqual(unittestSignature(oracle, ""), unittestSignature(equivalent, ""));
  assert.deepEqual(
    verifierSignature(verifier, equivalent, ""),
    unittestSignature(oracle, ""),
  );
  assert.deepEqual(unittestSignature("OK\n", ""), []);
  assert.deepEqual(unittestSignature("Ran 0 tests in 0.01s\nOK\n", ""), []);
});

test("pytest signature requires positive exact-path verbose evidence", () => {
  const verifier = [
    "python3",
    "-m",
    "pytest",
    "-vv",
    "-p",
    "no:cacheprovider",
    "tests/test_example.py",
  ];
  const oracle = `============================= test session starts ==============================
collecting ... collected 2 items

tests/test_example.py::test_alpha PASSED                         [ 50%]
tests/test_example.py::test_beta PASSED [100%]

============================== 2 passed in 0.01s ===============================
`;
  const expected = [
    "tests/test_example.py::test_alpha ... PASSED",
    "tests/test_example.py::test_beta ... PASSED",
    "collected 2 items",
    "2 passed",
  ];
  assert.deepEqual(pytestSignature(oracle, ""), expected);
  assert.deepEqual(verifierSignature(verifier, oracle, ""), expected);
  assert.deepEqual(
    verifierSignature(
      verifier,
      oracle.replaceAll("tests/test_example.py", "tests/test_other.py"),
      "",
    ),
    [],
  );
});

test("case check compares independent positive signatures", () => {
  const transcript = [
    "test_example (tests.Example.test_example) ... ok",
    "Ran 1 test in 0.01s",
    "OK",
    "",
  ].join("\n");
  assert.equal(
    isValidCaseCheck({
      caseId: "example-case",
      verifier: [
        "python3",
        "-m",
        "unittest",
        "tests.test_example",
        "-v",
      ],
      baseline: { revision: "base", returnCode: 1, stdout: "", stderr: "" },
      admittedSolution: {
        revision: "admitted",
        returnCode: 0,
        stdout: transcript,
        stderr: "",
      },
      oracle: {
        revision: "oracle",
        returnCode: 0,
        stdout: transcript.replace("0.01s", "9.99s"),
        stderr: "",
      },
    }),
    true,
  );
});

test("bridge score policy is corpus-bound and ignores timing noise", () => {
  const decoded = decodeCorpusCase(validWire());
  assert.equal(decoded.ok, true);
  if (!decoded.ok) return;
  const transcript = [
    "test_example (tests.Example.test_example) ... ok",
    "Ran 1 test in 0.01s",
    "OK",
    "",
  ].join("\n");
  const metadata = {
    case_id: decoded.value.id,
    base_sha: decoded.value.baseSha,
    oracle_sha: decoded.value.oracleSha,
    split: decoded.value.split,
    submission_paths: [...decoded.value.submissionPaths],
    verifier_paths: [...decoded.value.verifierPaths],
    verifier: [...decoded.value.verifier],
    timeout_seconds: decoded.value.timeoutSeconds,
    tags: [...decoded.value.tags],
  };
  const accepted = evaluateCandidateScore(decoded.value, metadata, {
    kind: "completed",
    returncode: 0,
    stdout: transcript,
    stderr: "",
  }, {
    kind: "completed",
    returncode: 0,
    stdout: transcript.replace("0.01s", "9.75s"),
    stderr: "",
  });
  assert.equal(accepted.kind, "scored");
  if (accepted.kind === "scored") {
    assert.equal(accepted.correct, true);
    assert.equal(accepted.oracle_signature_match, true);
  }

  const unbound = evaluateCandidateScore(
    decoded.value,
    { ...metadata, unexpected: true },
    {
      kind: "completed",
      returncode: 0,
      stdout: transcript,
      stderr: "",
    },
    {
      kind: "completed",
      returncode: 0,
      stdout: transcript,
      stderr: "",
    },
  );
  assert.deepEqual(unbound, {
    kind: "scored",
    correct: false,
    explanation: "sample metadata is not corpus-bound",
    returncode: null,
    oracle_signature_match: false,
  });
});

test("bridge protocol is versioned, exact, and transports paths only as data", () => {
  const request = decodeBridgeRequest({
    schema_version: "coding-corpus-bridge-request/v1",
    operation: "catalog",
    corpus: "/tmp/corpus;touch-not-executed.jsonl",
  });
  assert.equal(request.ok, true);

  const excess = decodeBridgeRequest({
    schema_version: "coding-corpus-bridge-request/v1",
    operation: "catalog",
    corpus: "/tmp/corpus.jsonl",
    shell: "touch /tmp/escaped",
  });
  assert.equal(excess.ok, false);

  const wrongVersion = decodeBridgeRequest({
    schema_version: "coding-corpus-bridge-request/v2",
    operation: "catalog",
    corpus: "/tmp/corpus.jsonl",
  });
  assert.equal(wrongVersion.ok, false);

  const oversizedUnicode = decodeBridgeRequest({
    schema_version: "coding-corpus-bridge-request/v1",
    operation: "score",
    corpus: "/tmp/corpus.jsonl",
    case_id: "example-case",
    metadata: {},
    oracle: {
      kind: "completed",
      returncode: 0,
      stdout: "😀".repeat(16_385),
      stderr: "",
    },
    candidate: {
      kind: "completed",
      returncode: 0,
      stdout: "ok",
      stderr: "",
    },
  });
  assert.equal(oversizedUnicode.ok, false);
  if (!oversizedUnicode.ok) {
    assert.match(oversizedUnicode.error.reason, /output exceeds/u);
  }
});
