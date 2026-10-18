export interface FieldError {
  loc: (string | number)[];
  msg: string;
  type?: string;
}
/** Backend error envelope: every non-2xx carries `error`; `detail` is the legacy shape. */
export interface ErrorBody {
  code: string;
  message: string;
  retryable: boolean;
  field: string | null;
  details: Record<string, unknown>;
}
export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
    public error: ErrorBody | null = null,
  ) {
    super(
      error?.message ??
        (typeof detail === "string" ? detail : `Request failed (${status})`),
    );
    this.name = "ApiError";
  }
  /** Stable machine-readable code, e.g. "not_found", "stale_question". */
  get code(): string | null {
    return this.error?.code ?? null;
  }
  get fields(): FieldError[] {
    const raw = Array.isArray(this.detail)
      ? this.detail
      : Array.isArray(this.error?.details?.fields)
        ? (this.error!.details.fields as unknown[])
        : [];
    return raw.filter(
      (x): x is FieldError =>
        !!x &&
        typeof x === "object" &&
        Array.isArray((x as FieldError).loc) &&
        typeof (x as FieldError).msg === "string",
    );
  }
}
export class StaleProposalError extends ApiError {
  constructor(
    public currentHash: string | null,
    public reason: string,
  ) {
    super(409, { code: "stale_proposal", current_hash: currentHash, reason });
    this.name = "StaleProposalError";
    this.message =
      "Terms changed since you opened this — review the new proposal.";
  }
}
