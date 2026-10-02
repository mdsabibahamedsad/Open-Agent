import { defineTool } from "@openagent/extension-sdk";

type Tok = number | string;

function tokenize(expr: string): Tok[] {
  const re = /\s*([0-9]+(?:\.[0-9]+)?|[+\-*/^(),])\s*/g;
  const out: Tok[] = [];
  let m: RegExpExecArray | null;
  let last = 0;
  while ((m = re.exec(expr))) {
    if (m.index !== last) throw new Error(`invalid character at offset ${last}`);
    last = re.lastIndex;
    out.push(/^[0-9]/.test(m[1]) ? Number(m[1]) : m[1]);
  }
  if (last !== expr.length) throw new Error(`invalid character at offset ${last}`);
  return out;
}

export function evaluateExpression(expr: string): number {
  if (expr.length > 500) throw new Error("expression too long");
  const toks = tokenize(expr);
  if (toks.length === 0) throw new Error("empty expression");
  let pos = 0;
  const peek = (): Tok | undefined => toks[pos];
  function parseExpr(): number {
    let v = parseTerm();
    for (;;) {
      const t = peek();
      if (t === "+") { pos++; v += parseTerm(); }
      else if (t === "-") { pos++; v -= parseTerm(); }
      else return v;
    }
  }
  function parseTerm(): number {
    let v = parseFactor();
    for (;;) {
      const t = peek();
      if (t === "*") { pos++; v *= parseFactor(); }
      else if (t === "/") { pos++; const d = parseFactor(); if (d === 0) throw new Error("division by zero"); v /= d; }
      else return v;
    }
  }
  function parseFactor(): number {
    const t = toks[pos++];
    if (typeof t === "number") return t;
    if (t === "(") { const v = parseExpr(); if (toks[pos++] !== ")") throw new Error("missing ')'"); return v; }
    if (t === "-") return -parseFactor();
    if (t === "+") return parseFactor();
    throw new Error(`unexpected token '${t}'`);
  }
  const v = parseExpr();
  if (pos !== toks.length) throw new Error("trailing input");
  if (!Number.isFinite(v)) throw new Error("non-finite result");
  return v;
}

export default defineTool({
  name: "calculator.evaluate",
  description: "Evaluate an arithmetic expression safely (no eval).",
  inputSchema: {
    type: "object",
    properties: { expression: { type: "string", maxLength: 500 } },
    required: ["expression"],
  },
  outputSchema: {
    type: "object",
    properties: { result: { type: "number" } },
    required: ["result"],
  },
  timeoutSeconds: 5,
  async handler(_ctx, args: { expression: string }) {
    return { result: evaluateExpression(args.expression) };
  },
});
