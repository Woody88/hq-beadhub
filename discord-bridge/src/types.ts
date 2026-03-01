/** Matches the ChatMessageEvent dataclass in beadhub events.py */
export interface ChatMessageEvent {
  workspace_id: string;
  type: "chat.message_sent";
  timestamp: string;
  project_slug: string | null;
  project_id: string;
  session_id: string;
  message_id: string;
  from_alias: string;
  to_aliases: string[];
  preview: string;
}

/** Any event from the events:* channels */
export interface BeadHubEvent {
  workspace_id: string;
  type: string;
  timestamp: string;
  project_slug?: string | null;
  [key: string]: unknown;
}

/** Message from the admin messages API */
export interface AdminMessage {
  message_id: string;
  from_agent: string;
  body: string;
  created_at: string;
}

/** Session from the admin sessions API */
export interface AdminSession {
  session_id: string;
  participants: { workspace_id: string; alias: string }[];
  last_message: string | null;
  last_from: string | null;
  last_activity: string | null;
  message_count: number;
}

/** Bridge → Orchestrator Deployment via Redis LIST (Discord messages) */
export interface OrchestratorInboxMessage {
  thread_id: string;
  session_id: string;
  author: string;
  message: string;
  timestamp: string;
}

/** Bridge → Orchestrator Deployment via Redis LIST (bdh chat messages) */
export interface OrchestratorChatInboxMessage {
  type: "bdh_chat";
  thread_id: string;
  from_alias: string;
  message: string;
  project_slug: string;
  project_id: string;
  repo_origin: string;
  chat_session_id: string;
  timestamp: string;
}

/** A file attachment included in an agent outbox message (base64-encoded) */
export interface AgentAttachment {
  /** Original filename (e.g. "screenshot.png") */
  filename: string;
  /** Base64-encoded file content */
  data: string;
}

/** @deprecated Use AgentAttachment */
export type OrchestratorAttachment = AgentAttachment;

/** Any agent → Bridge via Redis LIST (agent:outbox key) */
export interface AgentOutboxMessage {
  /** Agent alias — used to pick the webhook username/emoji */
  from_alias: string;
  thread_id: string;
  session_id: string;
  response: string;
  timestamp: string;
  /** Optional file attachments (base64-encoded). Files >8MB are rejected. */
  attachments?: AgentAttachment[];
}

/** Orchestrator Deployment → Bridge via Redis LIST (orchestrator:outbox key) */
export interface OrchestratorOutboxMessage {
  thread_id: string;
  session_id: string;
  response: string;
  timestamp: string;
  /** Optional file attachments (base64-encoded). Files >8MB are rejected. */
  attachments?: AgentAttachment[];
}

/** Source of a session mapping */
export type SessionSource = "beadhub" | "orchestrator" | "ai";

/** Bridge → AI Dispatcher via ai:inbox */
export interface AiInboxMessage {
  thread_id: string;
  author: string;
  message: string;
  timestamp: string;
}

/** AI Job → Bridge via ai:outbox */
export interface AiOutboxMessage {
  thread_id: string;
  response: string;
  timestamp: string;
}
