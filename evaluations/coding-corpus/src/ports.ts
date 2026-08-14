import { Context, Data, Effect } from "effect";

export type FileOperation =
  | "read_text"
  | "write_bytes"
  | "write_bytes_within_root"
  | "write_bytes_atomic"
  | "make_directory"
  | "make_temp_directory"
  | "remove";

export class FileFailure extends Data.TaggedError("FileFailure")<{
  readonly operation: FileOperation;
  readonly path: string;
  readonly reason: string;
}> {}

export interface FileStoreService {
  readonly readText: (
    path: string,
    options?: { readonly maxBytes?: number },
  ) => Effect.Effect<string, FileFailure>;
  readonly writeBytes: (
    path: string,
    content: Uint8Array,
  ) => Effect.Effect<void, FileFailure>;
  readonly writeBytesWithinRoot: (
    root: string,
    relativePath: string,
    content: Uint8Array,
    mode?: 0o644 | 0o755,
  ) => Effect.Effect<void, FileFailure>;
  readonly writeBytesAtomic: (
    path: string,
    content: Uint8Array,
  ) => Effect.Effect<void, FileFailure>;
  readonly makeDirectory: (
    path: string,
    options?: { readonly recursive?: boolean },
  ) => Effect.Effect<void, FileFailure>;
  readonly makeTempDirectory: (
    prefix: string,
  ) => Effect.Effect<string, FileFailure>;
  readonly remove: (
    path: string,
  ) => Effect.Effect<void, FileFailure>;
}

export const FileStore =
  Context.GenericTag<FileStoreService>("flrh/coding-corpus/FileStore");

export type CommandFailureReason =
  | "spawn_failed"
  | "output_limit"
  | "timeout";

export class CommandFailure extends Data.TaggedError("CommandFailure")<{
  readonly command: string;
  readonly reason: CommandFailureReason;
  readonly detail: string;
}> {}

export interface CommandSpec {
  readonly command: string;
  readonly args: readonly string[];
  readonly cwd: string;
  readonly environment?: Readonly<Record<string, string>>;
  readonly timeoutMs: number;
  readonly maxOutputBytes: number;
}

export interface CommandResult {
  readonly exitCode: number;
  readonly stdout: Uint8Array;
  readonly stderr: Uint8Array;
}

export interface CommandExecutorService {
  readonly run: (
    spec: CommandSpec,
  ) => Effect.Effect<CommandResult, CommandFailure>;
}

export const CommandExecutor =
  Context.GenericTag<CommandExecutorService>(
    "flrh/coding-corpus/CommandExecutor",
  );
