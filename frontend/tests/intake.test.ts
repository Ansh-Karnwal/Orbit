import { it, expect } from "vitest";
import { parseCreao, taskCreateSchema } from "@/lib/intake";
import { demoSeed } from "@/mocks/scenario";
it("validates CREAO data, defaults and manual provenance", () => {
  const s = demoSeed();
  const parsed = parseCreao(JSON.stringify(s), "run-123");
  expect(parsed.source).toBe("creao");
  expect(parsed.creao_ref).toBe("run-123");
});
it("rejects backwards windows, past windows and unsafe money", () => {
  const s = demoSeed();
  s.constraints.window_end = s.constraints.window_start;
  expect(taskCreateSchema.safeParse(s).success).toBe(false);
  s.constraints.window_start = "2020-01-01T00:00:00Z";
  expect(taskCreateSchema.safeParse(s).success).toBe(false);
  s.constraints.max_visit_charge_cents = 1.5;
  expect(taskCreateSchema.safeParse(s).success).toBe(false);
});
it("does not allow imported permission changes or invalid live handles", () => {
  const s = demoSeed();
  expect(() =>
    parseCreao(
      JSON.stringify({
        ...s,
        constraints: { ...s.constraints, approval_policy: "never" },
      }),
      "",
    ),
  ).toThrow();
  expect(taskCreateSchema.safeParse({ ...s, mode: "live" }).success).toBe(
    false,
  );
});
