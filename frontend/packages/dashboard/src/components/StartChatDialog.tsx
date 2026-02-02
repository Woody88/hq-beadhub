import { useState } from "react"
import { useQuery, useMutation } from "@tanstack/react-query"
import { useApi } from "../hooks/useApi"
import { MessageCircle, Loader2 } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "./ui/dialog"
import { Button } from "./ui/button"
import { Textarea } from "./ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select"
import { type ApiClient, type StartChatResponse } from "../lib/api"
import { useStore } from "../hooks/useStore"

const MAX_MESSAGE_LENGTH = 4000

interface StartChatDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onChatStarted: (response: StartChatResponse, targetAlias: string) => void
}

export function StartChatDialog({
  open,
  onOpenChange,
  onChatStarted,
}: StartChatDialogProps) {
  const api = useApi<ApiClient>()
  const { dashboardIdentity, identityLoading, identityError } = useStore()
  const [targetAlias, setTargetAlias] = useState("")
  const [message, setMessage] = useState("")
  const [error, setError] = useState<string | null>(null)

  const { data: workspacesData, isLoading: workspacesLoading } = useQuery({
    queryKey: ["workspaces-for-chat"],
    queryFn: () => api.listWorkspaces(),
    enabled: open,
  })

  // Filter out current workspace and offline workspaces
  const availableWorkspaces = (workspacesData?.workspaces || []).filter(
    (ws) =>
      ws.workspace_id !== dashboardIdentity?.workspace_id &&
      ws.status !== "offline"
  )

  const startChatMutation = useMutation({
    mutationFn: async () => {
      if (!dashboardIdentity) {
        throw new Error("Dashboard identity not initialized")
      }
      if (!targetAlias || !targetAlias.trim()) {
        throw new Error("Please select a workspace to chat with")
      }
      if (!message.trim()) {
        throw new Error("Please enter a message")
      }
      if (message.length > MAX_MESSAGE_LENGTH) {
        throw new Error(`Message exceeds ${MAX_MESSAGE_LENGTH} characters`)
      }
      return api.startChat(
        dashboardIdentity.workspace_id,
        dashboardIdentity.alias,
        [targetAlias.trim()],
        message.trim()
      )
    },
    onSuccess: (response) => {
      onChatStarted(response, targetAlias)
      resetForm()
      onOpenChange(false)
    },
    onError: (err: Error) => {
      setError(err.message)
    },
  })

  const resetForm = () => {
    setTargetAlias("")
    setMessage("")
    setError(null)
  }

  const handleOpenChange = (newOpen: boolean) => {
    if (!newOpen) {
      resetForm()
    }
    onOpenChange(newOpen)
  }

  const canSend =
    dashboardIdentity &&
    targetAlias &&
    message.trim() &&
    !startChatMutation.isPending &&
    !identityLoading &&
    !identityError

  const formDisabled = startChatMutation.isPending || identityLoading || !!identityError

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <MessageCircle className="h-4 w-4" />
            Start New Chat
          </DialogTitle>
          <DialogDescription>
            Start a real-time conversation with another workspace
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Identity loading state */}
          {identityLoading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground bg-muted p-3 rounded">
              <Loader2 className="h-4 w-4 animate-spin" />
              Initializing messaging identity...
            </div>
          )}

          {/* Identity error state */}
          {identityError && !identityLoading && (
            <div className="text-sm text-destructive bg-destructive/10 p-3 rounded">
              {identityError}
            </div>
          )}

          {/* Target workspace selector */}
          <div className="space-y-2">
            <label className="text-sm font-medium">Chat with</label>
            {workspacesLoading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading workspaces...
              </div>
            ) : availableWorkspaces.length === 0 ? (
              <div className="text-sm text-muted-foreground p-3 bg-muted rounded">
                No online workspaces available to chat with
              </div>
            ) : (
              <Select
                value={targetAlias}
                onValueChange={(value) => {
                  setTargetAlias(value)
                  setMessage("")
                  setError(null)
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select a workspace" />
                </SelectTrigger>
                <SelectContent>
                  {availableWorkspaces.map((ws) => (
                    <SelectItem key={ws.workspace_id} value={ws.alias}>
                      {ws.alias}
                      {ws.human_name && ` (${ws.human_name})`}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          {/* Message */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium">Message</label>
              <span className="text-xs text-muted-foreground">
                {message.length}/{MAX_MESSAGE_LENGTH}
              </span>
            </div>
            <Textarea
              placeholder="Enter your message to start the conversation..."
              value={message}
              onChange={(e) => {
                setMessage(e.target.value)
                if (error) setError(null)
              }}
              disabled={formDisabled}
              rows={4}
              maxLength={MAX_MESSAGE_LENGTH}
            />
          </div>

          {/* Error message */}
          {error && (
            <div className="text-sm text-destructive bg-destructive/10 p-2 rounded">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={startChatMutation.isPending}
          >
            Cancel
          </Button>
          <Button
            onClick={() => startChatMutation.mutate()}
            disabled={!canSend}
          >
            {startChatMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Starting...
              </>
            ) : (
              <>
                <MessageCircle className="h-4 w-4 mr-2" />
                Start Chat
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
