import { GitBranch, User, X } from "lucide-react"
import { Badge, Button } from "@beadhub/dashboard/components/ui"
import { useStore, cn } from "@beadhub/dashboard"

export function ScopeBanner() {
  const {
    repoFilter,
    setRepoFilter,
    ownerFilter,
    setOwnerFilter,
    createdByFilter,
    setCreatedByFilter,
  } = useStore()

  // Don't show if no filters are active
  if (!repoFilter && !ownerFilter && !createdByFilter) {
    return null
  }

  const handleClearRepo = () => {
    setRepoFilter(null)
    setOwnerFilter(null)
    setCreatedByFilter(null)
  }

  const handleClearOwner = () => {
    setOwnerFilter(null)
    setCreatedByFilter(null)
  }

  const handleClearCreatedBy = () => {
    setCreatedByFilter(null)
  }

  return (
    <div className="bg-primary/5 border-b border-primary/20 px-4 py-2">
      <div className="flex items-center gap-2 text-sm flex-wrap">
        <span className="text-muted-foreground font-medium">Viewing:</span>

        {repoFilter && (
          <Badge
            variant="secondary"
            className={cn(
              "gap-1.5 pl-2 pr-1 py-1 h-7",
              "bg-accent/10 hover:bg-accent/20 border-accent/30"
            )}
          >
            <GitBranch className="h-3.5 w-3.5" />
            <span className="font-medium">{repoFilter}</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-5 w-5 p-0 hover:bg-accent/20 rounded-full"
              onClick={handleClearRepo}
            >
              <X className="h-3 w-3" />
            </Button>
          </Badge>
        )}

        {ownerFilter && (
          <>
            <span className="text-muted-foreground">/</span>
            <Badge
              variant="secondary"
              className="gap-1.5 pl-2 pr-1 py-1 h-7"
            >
              <User className="h-3.5 w-3.5" />
              <span className="font-medium">{ownerFilter}</span>
              <Button
                variant="ghost"
                size="sm"
                className="h-5 w-5 p-0 hover:bg-secondary rounded-full"
                onClick={handleClearOwner}
              >
                <X className="h-3 w-3" />
              </Button>
            </Badge>
          </>
        )}

        {createdByFilter && (
          <>
            <span className="text-muted-foreground">/</span>
            <Badge
              variant="secondary"
              className="gap-1.5 pl-2 pr-1 py-1 h-7"
            >
              <User className="h-3.5 w-3.5" />
              <span className="font-medium">created by {createdByFilter}</span>
              <Button
                variant="ghost"
                size="sm"
                className="h-5 w-5 p-0 hover:bg-secondary rounded-full"
                onClick={handleClearCreatedBy}
              >
                <X className="h-3 w-3" />
              </Button>
            </Badge>
          </>
        )}
      </div>
    </div>
  )
}
