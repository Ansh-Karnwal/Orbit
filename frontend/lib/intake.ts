import { z } from "zod";
const iso = z.iso.datetime({ offset: true });
const timezone = z.string().refine((value) => {
  try {
    new Intl.DateTimeFormat("en", { timeZone: value });
    return true;
  } catch {
    return false;
  }
}, "Use a valid IANA timezone");
export const taskCreateSchema = z
  .object({
    outcome_text: z.string().trim().min(1, "Describe the outcome you want"),
    constraints: z.object({
      service: z.string().min(1),
      window_start: iso,
      window_end: iso,
      timezone,
      max_visit_charge_cents: z
        .number()
        .int()
        .positive()
        .max(Number.MAX_SAFE_INTEGER),
      require_diagnostic_fee_confirmed: z.boolean().default(true),
      require_cancellation_terms: z.boolean().default(true),
      approval_policy: z.literal("before_booking").default("before_booking"),
    }),
    providers: z
      .array(
        z.object({
          id: z.string().min(1),
          name: z.string().min(1),
          channel: z.enum(["imessage", "sms", "fixture"]).default("fixture"),
          handle: z.string().min(1),
          portal_url: z.url().nullable().default(null),
        }),
      )
      .min(1, "Add at least one provider")
      .max(10, "At most 10 providers per task"),
    limits: z
      .object({
        max_tool_actions: z.number().int().positive().default(40),
        max_runtime_s: z.number().int().positive().default(1800),
        max_llm_calls: z.number().int().positive().default(60),
        reply_timeout_s: z.number().int().positive().default(600),
      })
      .default({
        max_tool_actions: 40,
        max_runtime_s: 1800,
        max_llm_calls: 60,
        reply_timeout_s: 600,
      }),
    mode: z.enum(["fixture", "live"]).default("fixture"),
    source: z.enum(["manual", "creao", "demo_seed"]).default("manual"),
    creao_ref: z.string().nullable().default(null),
    user_contact: z
      .string()
      .trim()
      .min(1)
      .nullable()
      .optional()
      .transform((v) => v ?? null),
  })
  .superRefine((data, ctx) => {
    if (
      Date.parse(data.constraints.window_end) <=
      Date.parse(data.constraints.window_start)
    )
      ctx.addIssue({
        code: "custom",
        path: ["constraints", "window_end"],
        message: "End must be after start",
      });
    if (Date.parse(data.constraints.window_start) <= Date.now())
      ctx.addIssue({
        code: "custom",
        path: ["constraints", "window_start"],
        message: "Choose a future appointment window",
      });
    if (new Set(data.providers.map((p) => p.id)).size !== data.providers.length)
      ctx.addIssue({
        code: "custom",
        path: ["providers"],
        message: "Provider IDs must be unique",
      });
    if (
      data.user_contact &&
      data.providers.some((p) => p.handle === data.user_contact)
    )
      ctx.addIssue({
        code: "custom",
        path: ["user_contact"],
        message: "Your contact can't be one of the providers' handles",
      });
    if (
      data.mode === "live" &&
      data.providers.some(
        (p) => p.channel === "fixture" || p.handle.startsWith("fixture:"),
      )
    )
      ctx.addIssue({
        code: "custom",
        path: ["providers"],
        message:
          "Live mode requires consenting live provider handles from the backend seed or imported intake",
      });
  });
export function parseCreao(json: string, reference: string) {
  const raw: unknown = JSON.parse(json);
  if (!raw || typeof raw !== "object" || Array.isArray(raw))
    throw new Error("Paste a TaskCreate JSON object");
  return taskCreateSchema.parse({
    ...raw,
    source: "creao",
    creao_ref: reference.trim() || ("creao_ref" in raw ? raw.creao_ref : null),
  });
}
