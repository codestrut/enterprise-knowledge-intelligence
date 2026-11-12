export interface HealthResponse {
  status?: string | null;
  document_count?: number | null;
  chunk_count?: number | null;
  manifest_exists?: boolean | null;
  failed_document_count?: number | null;
}

export interface CurrentUserProfile {
  email: string;
  organisation: { id: string; name: string } | null;
  role: string;
  permissions: string[];
  platform_permissions: string[];
  platform_roles?: string[];
}

export interface DocumentRecord {
  document_id?: string;
  filename?: string;
  page_count?: number | null;
  chunk_count?: number | null;
  status?: string | null;
  sha256?: string;
  [key: string]: unknown;
}

export interface DocumentListResponse {
  count: number;
  documents: DocumentRecord[];
}

export interface UploadResponse {
  message?: string;
  document: DocumentRecord;
}

export interface DeleteResponse {
  message?: string;
  document_id: string;
  filename?: string;
  chunks_removed?: number;
  file_deleted: boolean;
  cleanup_required: boolean;
}

export interface QueryRequest {
  question: string;
  top_k: number;
}

export interface QuerySource {
  text?: string;
  score?: number | null;
  metadata?: QuerySourceMetadata;
}

export interface QuerySourceMetadata {
  source?: string;
  page?: string | number;
  document_id?: string;
  filename?: string;
  stored_filename?: string;
  chunk_id?: string | number;
  chunk_key?: string;
  [key: string]: unknown;
}

export interface QueryCitation {
  source_number: number;
  source: string;
  page: string | number;
  chunk_id: string | number;
}

export interface QuerySourceMapEntry {
  source: string;
  page: string | number;
  chunk_id: string | number;
}

export interface GroundingClaim {
  claim?: string;
  status?: string;
  reason?: string;
  supporting_passage?: string;
  atomic_claims?: AtomicGroundingClaim[];
  [key: string]: unknown;
}

export interface AtomicGroundingClaim {
  claim?: string;
  status?: string;
  sources?: GroundingSourceResult[];
}

export interface GroundingSourceResult {
  source_number?: number;
  label?: string;
  reason?: string;
  evidence?: GroundingEvidenceItem[];
  [key: string]: unknown;
}

export interface GroundingEvidenceItem {
  evidence?: string;
  label?: string;
  raw_label?: string;
  evidence_score?: number;
  [key: string]: unknown;
}

export interface QueryEvidence {
  sufficient?: boolean;
  score?: number | null;
  threshold?: number;
  reason?: string;
}

export interface GenerationRepair {
  attempted?: boolean;
  accepted?: boolean;
  reason?: string;
  mode?: string;
  initial_issue_count?: number;
  grounded_subset_used?: boolean;
  grounded_subset_claim_count?: number;
  initial_diagnostics?: Record<string, unknown>;
  repair_diagnostics?: Record<string, unknown>;
}

export interface QueryResponse {
  question?: string;
  answer: string;
  sources?: QuerySource[];
  source_map?: Record<string, QuerySourceMapEntry>;
  citations?: QueryCitation[];
  invalid_citations?: number[];
  grounding?: GroundingClaim[];
  evidence?: QueryEvidence;
  refused?: boolean;
  generation_repair?: GenerationRepair;
}

export interface PlatformOrganisation {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  status: string;
  initial_admin_email: string | null;
  provisioning_attempts: number;
  provisioning_started_at: string | null;
  provisioning_error_code: string | null;
  created_at: string | null;
}

export interface PlatformOrganisationListResponse { count: number; organisations: PlatformOrganisation[] }

export interface PlatformOverviewResponse {
  total_tenants: number;
  active_tenants: number;
  pending_tenants: number;
  provisioning_tenants: number;
  failed_tenants: number;
  suspended_tenants: number;
  total_documents: number;
  total_chunks: number;
}

export type PlatformRole =
  | "platform_super_administrator"
  | "platform_tenant_creator"
  | "platform_tenant_approver"
  | "platform_provisioning_operator";

export interface PlatformUser {
  id: string;
  email: string;
  is_active: boolean;
}

export interface PlatformUserSearchResponse {
  count: number;
  users: PlatformUser[];
}

export interface PlatformRoleAssignmentResponse {
  user_id: string;
  role: PlatformRole;
  already_assigned: boolean;
}

export interface PlatformRoleHolder {
  id: string;
  user_id: string;
  email: string;
  role: PlatformRole;
  assigned_at: string;
}

export interface PlatformRoleHolderListResponse {
  count: number;
  assignments: PlatformRoleHolder[];
}

export interface PlatformAuditEvent {
  id: string;
  actor_user_id: string | null;
  organisation_id: string | null;
  event_type: string;
  target_type: string | null;
  target_id: string | null;
  occurred_at: string;
  details: Record<string, JsonValue>;
}

export interface PlatformAuditEventListResponse {
  count: number;
  events: PlatformAuditEvent[];
}


export type TenantRole = "organisation_administrator" | "contributor" | "reader";

export interface TenantOverviewResponse {
  organisation_id: string;
  organisation_name: string;
  document_count: number;
  chunk_count: number;
  failed_document_count: number;
  member_count: number;
}

export interface TenantMember {
  id: string;
  user_id: string;
  email: string;
  role: TenantRole;
  is_active: boolean;
  created_at: string;
}

export interface TenantMemberListResponse {
  count: number;
  members: TenantMember[];
}

export interface TenantInvitation {
  id: string;
  recipient_email: string;
  role: TenantRole;
  invited_by_email: string;
  expires_at: string;
  created_at: string;
}

export interface TenantInvitationListResponse {
  count: number;
  invitations: TenantInvitation[];
}

export interface TenantInvitationCreateResponse {
  id: string;
  recipient_email: string;
  role: TenantRole;
  invitation_token: string | null;
  expires_at: string;
}

export interface TenantSettings {
  organisation_id: string;
  allowed_email_domains: string[];
  session_idle_timeout_minutes: number;
}

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface TenantAuditEvent {
  id: string;
  actor_user_id: string | null;
  organisation_id: string;
  event_type: string;
  target_type: string | null;
  target_id: string | null;
  occurred_at: string;
  details: Record<string, JsonValue>;
}

export interface TenantAuditEventListResponse {
  count: number;
  events: TenantAuditEvent[];
}
