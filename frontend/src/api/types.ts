export interface HealthResponse {
  status?: string | null;
  document_count?: number | null;
  chunk_count?: number | null;
  manifest_exists?: boolean | null;
  failed_document_count?: number | null;
}
