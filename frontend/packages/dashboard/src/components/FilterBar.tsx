import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { X, Filter, ChevronDown, ChevronUp } from "lucide-react"
import { Button } from "./ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select"
import { useApi } from "../hooks/useApi"
import { useStore } from "../hooks/useStore"
import type { ApiClient, WorkspacePresence } from "../lib/api"
import type { FilterBarProps } from "./types"

export function FilterBar(props: FilterBarProps) {
  const { disabled = false } = props
  const [expanded, setExpanded] = useState(false)
  const api = useApi<ApiClient>()
  const {
    repoFilter,
    setRepoFilter,
    ownerFilter,
    setOwnerFilter,
    clearFilters,
  } = useStore()

  // Fetch workspaces to get available options
  const { data: workspacesData } = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => api.listWorkspaces(),
    staleTime: 60000,
  })

  const workspaces: WorkspacePresence[] = workspacesData?.workspaces || []

  const repos = Array.from(
    new Set(
      workspaces
        .map((ws: WorkspacePresence) => ws.repo)
        .filter(Boolean)
    )
  ).sort() as string[]

  // Extract unique owners (human_name)
  const owners = Array.from(
    new Set(
      workspaces
        .filter((ws: WorkspacePresence) => !repoFilter || ws.repo === repoFilter)
        .map((ws: WorkspacePresence) => ws.human_name)
        .filter(Boolean)
    )
  ).sort() as string[]

  const hasFilters = repoFilter || ownerFilter
  const activeFilterCount = [repoFilter, ownerFilter].filter(Boolean).length

  // Always show filters, but disable when no data available
  const noRepoData = repos.length === 0
  const noOwnerData = owners.length === 0

  // Filter hierarchy: Repo > Owner
  // Changing a parent filter clears all descendant filters
  const handleRepoChange = (value: string) => {
    if (value === "__all__") {
      setRepoFilter(null)
      setOwnerFilter(null)
    } else {
      setRepoFilter(value)
      setOwnerFilter(null)
    }
  }

  const handleOwnerChange = (value: string) => {
    if (value === "__all__") {
      setOwnerFilter(null)
    } else {
      setOwnerFilter(value)
    }
  }

  const filterControls = (
    <>
      {/* Repo Filter */}
      <Select
        value={repoFilter || "__all__"}
        onValueChange={handleRepoChange}
        disabled={disabled || noRepoData}
      >
        <SelectTrigger className="h-8 w-full sm:w-[160px] text-xs">
          <SelectValue placeholder="All Repos" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__all__">All Repos</SelectItem>
          {repos.map((repo) => (
            <SelectItem key={repo} value={repo}>
              {repo}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Owner Filter */}
      <Select
        value={ownerFilter || "__all__"}
        onValueChange={handleOwnerChange}
        disabled={disabled || noOwnerData}
      >
        <SelectTrigger className="h-8 w-full sm:w-[140px] text-xs">
          <SelectValue placeholder="All Owners" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__all__">All Owners</SelectItem>
          {owners.map((owner) => (
            <SelectItem key={owner} value={owner}>
              {owner}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Clear All */}
      {hasFilters && (
        <Button
          variant="ghost"
          size="sm"
          className="h-8 px-2 text-xs"
          onClick={clearFilters}
          disabled={disabled}
        >
          <X className="h-3.5 w-3.5 mr-1" />
          Clear
        </Button>
      )}
    </>
  )

  return (
    <div className="py-2">
      {/* Mobile: Collapsible toggle */}
      <div className="sm:hidden">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring transition-colors w-full"
          aria-expanded={expanded}
          aria-controls="mobile-filter-controls"
          aria-label="Toggle filters"
        >
          <Filter className="h-3.5 w-3.5" />
          <span>Filters</span>
          {activeFilterCount > 0 && (
            <span className="px-1.5 py-0.5 bg-primary text-primary-foreground rounded text-xs font-medium">
              {activeFilterCount}
            </span>
          )}
          {expanded ? (
            <ChevronUp className="h-3.5 w-3.5 ml-auto" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 ml-auto" />
          )}
        </button>
        {expanded && (
          <div id="mobile-filter-controls" className="flex flex-col gap-2 mt-2">
            {filterControls}
          </div>
        )}
      </div>

      {/* Desktop: Inline filters */}
      <div className="hidden sm:flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Filter className="h-3.5 w-3.5" />
          <span>Filter:</span>
        </div>
        {filterControls}
      </div>
    </div>
  )
}
