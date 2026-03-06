/** Discord Bridge → Dispatcher via ai:inbox */
export interface AiInboxMessage {
  thread_id: string;
  author: string;
  message: string;
  timestamp: string;
}

/** Dispatcher → AI Job via ai-job:inbox */
export interface AiJobInboxMessage {
  thread_id: string;
  message: string;
  session_uuid: string;
  timestamp: string;
}

/** AI Job → Discord Bridge via ai:outbox */
export interface AiOutboxMessage {
  thread_id: string;
  response: string;
  timestamp: string;
}

/** BeadHub Redis pub/sub event (events:* channel) */
export interface BeadHubEvent {
  type: string;
}

/** chat.message_sent event from BeadHub */
export interface ChatMessageEvent extends BeadHubEvent {
  type: "chat.message_sent";
  message_id: string;
  session_id: string;
  from_alias: string;
  to_aliases: string[];
  body: string;
  created_at: string;
}
