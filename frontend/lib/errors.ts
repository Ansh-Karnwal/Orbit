export interface FieldError {
  loc: (string | number)[];
  msg: string;
  type?: string;
}
export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `Request failed (${status})`);
    this.name = "ApiError";
  }
  get fields(): FieldError[] {
    return Array.isArray(this.detail)
      ? this.detail.filter(
          (x): x is FieldError =>
            !!x && Array.isArray(x.loc) && typeof x.msg === "string",
        )
      : [];
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
