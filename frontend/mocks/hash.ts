import { sha256 } from "js-sha256";
import type { Proposal } from "@/lib/types";
/** Mock-only equivalent of Proposal.compute_hash(). Live hashes come from the API. */
export function mockProposalHash(proposal: Proposal): string {
  const sorted = Object.fromEntries(
    Object.keys(proposal)
      .sort()
      .map((key) => [key, proposal[key as keyof Proposal]]),
  );
  const json = JSON.stringify(sorted).replace(
    /[\u007f-\uffff]/g,
    (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`,
  );
  return sha256(json);
}
