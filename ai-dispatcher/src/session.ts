import { v5 as uuidv5 } from "uuid";

/**
 * Fixed namespace UUID for deterministic thread ID → session UUID mapping.
 * Generated once, never changes. This ensures the same Discord thread
 * always maps to the same Claude session UUID.
 */
const NAMESPACE = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";

/**
 * Deterministic UUID v5 from a Discord thread ID (snowflake).
 * Same thread always produces the same session UUID, so Claude
 * resumes the correct conversation from the PVC.
 */
export function threadIdToSessionUuid(threadId: string): string {
  return uuidv5(threadId, NAMESPACE);
}
