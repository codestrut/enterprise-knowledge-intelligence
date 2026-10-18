export interface HealthResponse {
  status?: string | null;
  document_count?: number | null;
  chunk_count?: number | null;
  manifest_exists?: boolean | null;
  failed_document_count?: number | null;
}

export interface CurrentUserProfile {
  email: string;
  organisation: { id: string; name: string };
  role: string;
  permissions: string[];
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
