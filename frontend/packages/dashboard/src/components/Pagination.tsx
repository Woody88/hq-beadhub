import { Loader2 } from "lucide-react"
import { Button } from "./ui/button"
import { cn } from "../lib/utils"

export interface PaginationProps {
  /** Callback when user requests more items */
  onLoadMore: () => void
  /** Whether there are more items available */
  hasMore: boolean
  /** Whether items are currently being loaded */
  isLoading: boolean
  /** Current number of items displayed (optional) */
  itemCount?: number
  /** Total number of items available (optional) */
  totalCount?: number
  /** Additional CSS classes */
  className?: string
}

/**
 * Pagination component for loading more items in list views.
 *
 * Uses a "Load more" button pattern that fits infinite scroll UX.
 * Hides completely when there are no more items to load.
 */
export function Pagination({
  onLoadMore,
  hasMore,
  isLoading,
  itemCount,
  totalCount,
  className,
}: PaginationProps) {
  // Don't render if no more items
  if (!hasMore) {
    return null
  }

  return (
    <div className={cn("flex flex-col items-center gap-2 py-4", className)}>
      {/* Item count display */}
      {itemCount !== undefined && (
        <p className="text-sm text-muted-foreground">
          {totalCount !== undefined
            ? `${itemCount} of ${totalCount}`
            : `${itemCount} items`}
        </p>
      )}

      {/* Load more button */}
      <Button
        variant="outline"
        onClick={onLoadMore}
        disabled={isLoading}
        aria-label={isLoading ? "Loading more items" : "Load more items"}
      >
        {isLoading ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
            Loading...
          </>
        ) : (
          "Load more"
        )}
      </Button>
    </div>
  )
}
