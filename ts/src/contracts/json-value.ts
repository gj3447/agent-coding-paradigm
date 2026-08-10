/**
 * JSON value model for the flrh-cjson/1 profile.
 *
 * Integers are bigint (int64 fidelity), floats keep their source lexeme so the
 * canonicalizer can reject them the way the Python oracle does, and objects are
 * Maps so "__proto__"-like keys and insertion order behave exactly like Python
 * dicts.
 */

export class JsonFloat {
  readonly source: string;
  constructor(source: string) {
    this.source = source;
  }
}

export type JsonValue =
  | null
  | boolean
  | bigint
  | string
  | JsonFloat
  | JsonValue[]
  | JsonObject;

export type JsonObject = Map<string, JsonValue>;

export const isJsonObject = (value: JsonValue): value is JsonObject => value instanceof Map;

export const jsonObject = (entries: ReadonlyArray<readonly [string, JsonValue]>): JsonObject =>
  new Map(entries);

export const deepCopyJson = (value: JsonValue): JsonValue => {
  if (Array.isArray(value)) {
    return value.map(deepCopyJson);
  }
  if (value instanceof Map) {
    const copy: JsonObject = new Map();
    for (const [key, item] of value) {
      copy.set(key, deepCopyJson(item));
    }
    return copy;
  }
  return value;
};
