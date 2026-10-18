/** Mirrors backend/app/core/schemas.py. ISO dates are strings; USD values are integer cents. */
export type TaskStatus =
  | "DRAFT"
  | "PLANNING"
  | "RUNNING"
  | "AWAITING_APPROVAL"
  | "WAITING_EXTERNAL"
  | "BLOCKED"
  | "VERIFYING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";
export type FactStatus = "proposed" | "confirmed" | "superseded" | "rejected";
export type StepKind =
  | "send_inquiry"
  | "await_reply"
  | "extract_quote"
  | "compare_quotes"
  | "read_availability"
  | "request_approval"
  | "submit_booking"
  | "reconcile_booking"
  | "verify"
  | "summarize";
export type StepState =
  | "pending"
  | "ready"
  | "running"
  | "succeeded"
  | "failed"
  | "blocked"
  | "skipped";
export type Verdict = "PASS" | "FAIL" | "INSUFFICIENT_EVIDENCE";
export type ClaimLevel =
  | "message_submitted"
  | "message_delivered"
  | "slot_offered"
  | "booking_request_submitted"
  | "booking_verified";
export type Mode = "fixture" | "live";
export type AdapterName =
  | "photon"
  | "browser_use"
  | "creao"
  | "fixture_messaging"
  | "fixture_browser"
  | "demo"
  | "orbit";
export type EvidenceKind =
  | "message_out"
  | "message_in"
  | "delivery_receipt"
  | "screenshot"
  | "browser_trace"
  | "availability"
  | "portal_confirmation"
  | "creao_output";
export interface Constraints {
  service: string;
  window_start: string;
  window_end: string;
  timezone: string;
  max_visit_charge_cents: number;
  require_diagnostic_fee_confirmed: boolean;
  require_cancellation_terms: boolean;
  approval_policy: "before_booking";
}
export interface Limits {
  max_tool_actions: number;
  max_runtime_s: number;
  max_llm_calls: number;
  reply_timeout_s: number;
}
export interface ProviderSpec {
  id: string;
  name: string;
  channel: "imessage" | "sms" | "fixture";
  handle: string;
  portal_url: string | null;
}
export interface TaskCreate {
  outcome_text: string;
  constraints: Constraints;
  providers: ProviderSpec[];
  limits: Limits;
  mode: Mode;
  source: "manual" | "creao" | "demo_seed";
  creao_ref: string | null;
}
export interface Task {
  id: string;
  outcome_text: string;
  constraints: Constraints;
  limits: Limits;
  mode: Mode;
  status: TaskStatus;
  status_reason: string;
  source: string;
  creao_ref: string | null;
  summary: string | null;
  created_at: string;
  updated_at: string;
}
export interface ContextFact {
  id: string;
  task_id: string;
  key: string;
  value: unknown;
  currency: string | null;
  scope: string | null;
  source_id: string;
  observed_at: string;
  valid_until: string | null;
  status: FactStatus;
  version: number;
  supersedes: string | null;
}
export interface Conflict {
  kind:
    | "value_changed"
    | "budget_violation"
    | "window_violation"
    | "missing_required"
    | "contradiction";
  key: string;
  provider_id: string | null;
  old_value: unknown;
  new_value: unknown;
  detail: string;
}
export interface IngestResult {
  fact: ContextFact;
  superseded: ContextFact | null;
  conflicts: Conflict[];
  changed: boolean;
}
export interface ContextPacket {
  task_id: string;
  step_kind: StepKind;
  outcome: string;
  constraints: Constraints;
  domain_rules: string[];
  facts: ContextFact[];
  unresolved: Conflict[];
  allowed_scope: string[];
  required_output: Record<string, unknown>;
  required_evidence: string[];
}
export interface PlanStep {
  id: string;
  task_id: string;
  kind: StepKind;
  provider_id: string | null;
  depends_on: string[];
  state: StepState;
  attempts: number;
  max_attempts: number;
  idempotency_key: string;
  not_before: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
  plan_version: number;
  created_at: string;
  updated_at: string;
}
export interface ToolAction {
  id: string;
  task_id: string;
  step_id: string;
  adapter: AdapterName;
  operation: string;
  idempotency_key: string;
  request: Record<string, unknown>;
  status: "started" | "succeeded" | "failed" | "ambiguous";
  provider_ref: string | null;
  result: Record<string, unknown> | null;
  evidence_ids: string[];
  started_at: string;
  finished_at: string | null;
}
export interface InboundEvent {
  id: string;
  source: "photon" | "fixture" | "demo";
  external_id: string;
  task_id: string | null;
  provider_id: string | null;
  sender_handle: string | null;
  text: string;
  payload: Record<string, unknown>;
  received_at: string;
  processed: boolean;
}
export interface Proposal {
  task_id: string;
  provider_id: string;
  provider_name: string;
  service: string;
  slot_start: string;
  slot_end: string;
  visit_charge_cents: number;
  fee_scope: string;
  cancellation_terms: string;
  repair_cost_known: boolean;
  terms_version: number;
  source_fact_ids: string[];
}
export interface Approval {
  id: string;
  task_id: string;
  proposal: Proposal;
  proposal_hash: string;
  status: "requested" | "approved" | "rejected" | "invalidated" | "expired";
  approver: string | null;
  requested_at: string;
  decided_at: string | null;
  expires_at: string | null;
  invalidated_reason: string | null;
}
export interface ApprovalDecisionIn {
  proposal_hash: string;
  decision: "approved" | "rejected";
  approver: string;
}
export interface ConfirmationExtract {
  confirmation_id: string;
  provider_id: string;
  service: string;
  slot_start: string;
  slot_end: string;
  visit_charge_cents: number;
  cancellation_terms: string;
  orbit_ref: string;
}
export interface EvidenceArtifact {
  id: string;
  task_id: string;
  kind: EvidenceKind;
  source: AdapterName;
  uri: string | null;
  mime_type: string | null;
  sha256: string | null;
  extracted: Record<string, unknown>;
  claim_level: ClaimLevel | null;
  is_fixture: boolean;
  provider_ref: string | null;
  captured_at: string;
}
export interface SendResult {
  provider_ref: string | null;
  status: "submitted" | "delivered" | "failed";
  evidence_ids: string[];
  error: string | null;
}
export interface Slot {
  start: string;
  end: string;
  label: string;
}
export interface AvailabilityResult {
  slots: Slot[];
  evidence_ids: string[];
  session_ref: string | null;
  error: string | null;
}
export interface BookingRequest {
  task_id: string;
  proposal: Proposal;
  approval_id: string;
  orbit_ref: string;
  customer_name: string;
  customer_contact: string;
}
export interface BookingResult {
  status: "confirmed" | "submitted_unconfirmed" | "ambiguous" | "failed";
  confirmation: ConfirmationExtract | null;
  evidence_ids: string[];
  session_ref: string | null;
  error: string | null;
}
export interface PredicateResult {
  name: string;
  passed: boolean | null;
  detail: string;
  evidence_ids: string[];
}
export interface VerificationResult {
  id: string;
  task_id: string;
  approval_id: string | null;
  predicates: PredicateResult[];
  verdict: Verdict;
  explanation: string;
  created_at: string;
}
export interface TimelineEvent {
  id: string;
  task_id: string;
  seq: number;
  type: string;
  message: string;
  data: Record<string, unknown>;
  at: string;
}
export interface TaskView {
  task: Task;
  providers: ProviderSpec[];
  facts: ContextFact[];
  eligibility: Record<string, string[]>;
  steps: PlanStep[];
  approvals: Approval[];
  current_proposal: Proposal | null;
  evidence: EvidenceArtifact[];
  verification: VerificationResult | null;
  timeline: TimelineEvent[];
  integrations: Record<string, string>;
}
export interface DemoInjectIn {
  task_id: string;
  provider_id: string;
  text: string;
  external_id: string | null;
}
export interface PortalFaultIn {
  mode:
    "none" | "timeout_after_submit" | "mismatch" | "no_confirmation" | "down";
}
export interface Health {
  ok: boolean;
  mode: Mode;
  integrations: Record<string, string>;
}
export interface DemoResetIn {
  create_task: boolean;
  mode: Mode;
}
export interface DemoResetResult {
  task_id: string | null;
}
export interface DemoInjectResult {
  inbound_id: string;
  created: boolean;
}
