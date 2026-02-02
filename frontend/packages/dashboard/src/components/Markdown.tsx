import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "../lib/utils"

interface MarkdownProps {
  children: string
  className?: string
}

export function Markdown({ children, className }: MarkdownProps) {
  return (
    <div
      className={cn(
        "prose prose-sm dark:prose-invert max-w-none",
        "prose-headings:text-foreground prose-headings:font-semibold",
        "prose-h1:text-lg prose-h2:text-base prose-h3:text-sm",
        "prose-p:text-muted-foreground prose-p:my-2",
        "prose-li:text-muted-foreground prose-li:my-0.5",
        "prose-code:text-xs prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded",
        "prose-code:before:content-[''] prose-code:after:content-['']",
        "prose-pre:bg-muted prose-pre:text-foreground prose-pre:text-xs",
        "prose-a:text-primary prose-a:no-underline hover:prose-a:underline",
        "prose-strong:text-foreground",
        className
      )}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  )
}
