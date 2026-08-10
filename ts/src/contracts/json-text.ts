/**
 * Lexical JSON parser preserving the integer/float distinction and int64
 * precision that JSON.parse destroys. Grammar mirrors Python's json.loads:
 * RFC 8259 plus the NaN/Infinity/-Infinity constants, which json.loads always
 * accepts and hands to the canonicalizer as floats (rejected there in-band as
 * FLOAT_FORBIDDEN with a JSON Pointer, not at the parser). Duplicate object
 * keys keep the last value; lone-surrogate \u escapes are preserved in the
 * decoded string (rejected later by the canonicalizer, not the parser).
 */

import { JsonFloat, type JsonObject, type JsonValue } from "./json-value";

export class JsonParseError extends Error {
  readonly position: number;
  constructor(message: string, position: number) {
    super(`${message} at position ${position}`);
    this.position = position;
  }
}

const WHITESPACE = new Set([" ", "\t", "\n", "\r"]);

class Parser {
  private readonly text: string;
  private index = 0;

  constructor(text: string) {
    this.text = text;
  }

  parse(): JsonValue {
    const value = this.parseValue();
    this.skipWhitespace();
    if (this.index !== this.text.length) {
      throw new JsonParseError("trailing content", this.index);
    }
    return value;
  }

  private skipWhitespace(): void {
    while (this.index < this.text.length && WHITESPACE.has(this.text[this.index] as string)) {
      this.index += 1;
    }
  }

  private parseValue(): JsonValue {
    this.skipWhitespace();
    const ch = this.text[this.index];
    if (ch === undefined) {
      throw new JsonParseError("unexpected end of input", this.index);
    }
    if (ch === "{") return this.parseObject();
    if (ch === "[") return this.parseArray();
    if (ch === '"') return this.parseString();
    for (const constant of ["NaN", "Infinity", "-Infinity"]) {
      if (this.text.startsWith(constant, this.index)) {
        this.index += constant.length;
        return new JsonFloat(constant);
      }
    }
    if (ch === "-" || (ch >= "0" && ch <= "9")) return this.parseNumber();
    if (this.text.startsWith("true", this.index)) {
      this.index += 4;
      return true;
    }
    if (this.text.startsWith("false", this.index)) {
      this.index += 5;
      return false;
    }
    if (this.text.startsWith("null", this.index)) {
      this.index += 4;
      return null;
    }
    throw new JsonParseError(`unexpected character ${JSON.stringify(ch)}`, this.index);
  }

  private parseObject(): JsonObject {
    const result: JsonObject = new Map();
    this.index += 1;
    this.skipWhitespace();
    if (this.text[this.index] === "}") {
      this.index += 1;
      return result;
    }
    for (;;) {
      this.skipWhitespace();
      if (this.text[this.index] !== '"') {
        throw new JsonParseError("expected string key", this.index);
      }
      const key = this.parseString();
      this.skipWhitespace();
      if (this.text[this.index] !== ":") {
        throw new JsonParseError("expected ':'", this.index);
      }
      this.index += 1;
      result.set(key, this.parseValue());
      this.skipWhitespace();
      const ch = this.text[this.index];
      if (ch === ",") {
        this.index += 1;
        continue;
      }
      if (ch === "}") {
        this.index += 1;
        return result;
      }
      throw new JsonParseError("expected ',' or '}'", this.index);
    }
  }

  private parseArray(): JsonValue[] {
    const result: JsonValue[] = [];
    this.index += 1;
    this.skipWhitespace();
    if (this.text[this.index] === "]") {
      this.index += 1;
      return result;
    }
    for (;;) {
      result.push(this.parseValue());
      this.skipWhitespace();
      const ch = this.text[this.index];
      if (ch === ",") {
        this.index += 1;
        continue;
      }
      if (ch === "]") {
        this.index += 1;
        return result;
      }
      throw new JsonParseError("expected ',' or ']'", this.index);
    }
  }

  private parseString(): string {
    let out = "";
    this.index += 1;
    for (;;) {
      const ch = this.text[this.index];
      if (ch === undefined) {
        throw new JsonParseError("unterminated string", this.index);
      }
      if (ch === '"') {
        this.index += 1;
        return out;
      }
      if (ch === "\\") {
        const escape = this.text[this.index + 1];
        this.index += 2;
        switch (escape) {
          case '"':
            out += '"';
            break;
          case "\\":
            out += "\\";
            break;
          case "/":
            out += "/";
            break;
          case "b":
            out += "\b";
            break;
          case "f":
            out += "\f";
            break;
          case "n":
            out += "\n";
            break;
          case "r":
            out += "\r";
            break;
          case "t":
            out += "\t";
            break;
          case "u": {
            const hex = this.text.slice(this.index, this.index + 4);
            if (!/^[0-9a-fA-F]{4}$/.test(hex)) {
              throw new JsonParseError("invalid \\u escape", this.index);
            }
            out += String.fromCharCode(Number.parseInt(hex, 16));
            this.index += 4;
            break;
          }
          default:
            throw new JsonParseError("invalid escape", this.index - 1);
        }
        continue;
      }
      const code = ch.charCodeAt(0);
      if (code < 0x20) {
        throw new JsonParseError("unescaped control character", this.index);
      }
      out += ch;
      this.index += 1;
    }
  }

  private parseNumber(): bigint | JsonFloat {
    const match = /^-?(?:0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?/.exec(
      this.text.slice(this.index),
    );
    if (match === null || match[0] === "") {
      throw new JsonParseError("invalid number", this.index);
    }
    const lexeme = match[0];
    this.index += lexeme.length;
    if (match[1] !== undefined || match[2] !== undefined) {
      return new JsonFloat(lexeme);
    }
    return BigInt(lexeme);
  }
}

export const parseJsonText = (text: string): JsonValue => new Parser(text).parse();
