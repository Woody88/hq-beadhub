import { useMemo, useState } from "react"
import { BookOpen, Check, Copy, RefreshCw } from "lucide-react"
import { Button, Card, CardContent, CardHeader, CardTitle } from "@beadhub/dashboard/components/ui"
import { cn } from "@beadhub/dashboard"

const PRIMARY_COMMAND = "bdh :init"
const DASHBOARD_COMMAND = "bdh :dashboard"

export function GettingStartedPage() {
  const [showExpanded, setShowExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  const expandedExample = useMemo(() => {
    const user = typeof window !== "undefined" ? (window as unknown as { __bh_user?: string }).__bh_user : undefined
    const human = user || "$USER"
    return `bdh :init --project demo --alias dev-01 --human "${human}"`
  }, [])

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(PRIMARY_COMMAND)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard may be unavailable in some browser contexts; ignore.
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Welcome to BeadHub</h1>
        <p className="text-sm text-muted-foreground">
          Register your first workspace to start seeing coordination data in the dashboard.
        </p>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <BookOpen className="h-4 w-4" />
            Getting started (OSS)
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <div className="space-y-2">
            <p className="text-muted-foreground">
              From a git repo checkout, run:
            </p>
            <div className="flex items-start gap-2">
              <pre className="flex-1 rounded-md bg-muted p-3 text-xs whitespace-pre-wrap font-mono">
                {PRIMARY_COMMAND}
              </pre>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="shrink-0"
                onClick={handleCopy}
                aria-label="Copy command"
              >
                {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              </Button>
            </div>

            <button
              type="button"
              className={cn(
                "text-xs text-muted-foreground hover:text-foreground underline underline-offset-4",
                showExpanded && "text-foreground"
              )}
              onClick={() => setShowExpanded((v) => !v)}
            >
              {showExpanded ? "Hide example with flags" : "Show example with flags"}
            </button>

            {showExpanded && (
              <pre className="rounded-md bg-muted p-3 text-xs whitespace-pre-wrap font-mono">
                {expandedExample}
              </pre>
            )}
          </div>

          <div className="space-y-2">
            <p className="text-muted-foreground">
              Then refresh the dashboard. You should see your workspace appear, and chat/mail actions will unlock.
            </p>
            <p className="text-muted-foreground">
              If the UI prompts for authentication, run <span className="font-mono text-xs text-foreground">{DASHBOARD_COMMAND}</span>{" "}
              to open the dashboard and store your API key in this browser (or paste the key from{" "}
              <span className="font-mono">~/.config/aw/config.yaml</span> once).
            </p>
            <div className="flex gap-2">
              <Button type="button" onClick={() => window.location.reload()}>
                <RefreshCw className="h-4 w-4 mr-2" />
                Refresh dashboard
              </Button>
            </div>
          </div>

          <div className="text-xs text-muted-foreground">
            Tips: see <span className="font-mono">README.md</span> for quickstart and{" "}
            <span className="font-mono">docs/deployment.md</span> for trusted-network guidance.
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
