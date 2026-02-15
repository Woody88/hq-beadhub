import { cn } from "../lib/utils"

function formatTimestamp(dateStr: string): string {
  const date = new Date(dateStr)
  const pad = (n: number) => n.toString().padStart(2, "0")
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export interface ChatBubbleProps {
  fromAlias: string
  body: string
  timestamp?: string
  alignRight?: boolean
  senderLeaving?: boolean
}

export function ChatBubble({
  fromAlias,
  body,
  timestamp,
  alignRight = false,
  senderLeaving,
}: ChatBubbleProps) {
  return (
    <div
      className={cn(
        "max-w-[85%] chat-bubble-enter",
        alignRight ? "self-end" : "self-start"
      )}
    >
      {/* Header with agent name and timestamp */}
      <div
        className={cn(
          "flex items-center gap-2 mb-1",
          alignRight && "justify-end"
        )}
      >
        {/* For right-aligned, timestamp comes first */}
        {alignRight && timestamp && (
          <span className="text-[11px] text-muted-foreground/70">
            {formatTimestamp(timestamp)}
          </span>
        )}
        <span
          className={cn(
            "font-mono text-xs font-semibold",
            alignRight ? "text-emerald-600 dark:text-emerald-400" : "text-primary"
          )}
        >
          {fromAlias}
        </span>
        {/* For left-aligned, timestamp comes after */}
        {!alignRight && timestamp && (
          <span className="text-[11px] text-muted-foreground/70">
            {formatTimestamp(timestamp)}
          </span>
        )}
      </div>

      {/* Message bubble */}
      <div
        className={cn(
          "px-4 py-3 text-sm leading-relaxed",
          alignRight
            ? "bg-gradient-to-br from-emerald-50 to-emerald-100 dark:from-emerald-950/50 dark:to-emerald-900/50 border border-emerald-200 dark:border-emerald-800 rounded-2xl rounded-br-sm"
            : "bg-card border border-border rounded-2xl rounded-bl-sm"
        )}
      >
        <p className="whitespace-pre-wrap break-words">{body}</p>
        {senderLeaving && (
          <p className="text-xs text-muted-foreground/60 italic mt-2">
            [{fromAlias} has left the conversation]
          </p>
        )}
      </div>
    </div>
  )
}
