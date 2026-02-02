import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Pagination } from "@beadhub/dashboard/components"

describe("Pagination component", () => {
  it("renders load more button when hasMore is true", () => {
    render(
      <Pagination
        onLoadMore={() => {}}
        hasMore={true}
        isLoading={false}
      />
    )
    expect(screen.getByRole("button", { name: /load more/i })).toBeInTheDocument()
  })

  it("does not render when hasMore is false", () => {
    render(
      <Pagination
        onLoadMore={() => {}}
        hasMore={false}
        isLoading={false}
      />
    )
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
  })

  it("shows loading state when isLoading is true", () => {
    render(
      <Pagination
        onLoadMore={() => {}}
        hasMore={true}
        isLoading={true}
      />
    )
    const button = screen.getByRole("button")
    expect(button).toBeDisabled()
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it("calls onLoadMore when button is clicked", async () => {
    const user = userEvent.setup()
    const onLoadMore = vi.fn()

    render(
      <Pagination
        onLoadMore={onLoadMore}
        hasMore={true}
        isLoading={false}
      />
    )

    await user.click(screen.getByRole("button", { name: /load more/i }))
    expect(onLoadMore).toHaveBeenCalledTimes(1)
  })

  it("does not call onLoadMore when loading", async () => {
    const user = userEvent.setup()
    const onLoadMore = vi.fn()

    render(
      <Pagination
        onLoadMore={onLoadMore}
        hasMore={true}
        isLoading={true}
      />
    )

    // Button should be disabled, so click should not trigger callback
    const button = screen.getByRole("button")
    await user.click(button)
    expect(onLoadMore).not.toHaveBeenCalled()
  })

  it("displays item count when provided", () => {
    render(
      <Pagination
        onLoadMore={() => {}}
        hasMore={true}
        isLoading={false}
        itemCount={25}
        totalCount={100}
      />
    )
    expect(screen.getByText("25 of 100")).toBeInTheDocument()
  })

  it("displays only current count when total is unknown", () => {
    render(
      <Pagination
        onLoadMore={() => {}}
        hasMore={true}
        isLoading={false}
        itemCount={25}
      />
    )
    expect(screen.getByText("25 items")).toBeInTheDocument()
  })

  it("does not display item count when not provided", () => {
    render(
      <Pagination
        onLoadMore={() => {}}
        hasMore={true}
        isLoading={false}
      />
    )
    expect(screen.queryByText(/items/)).not.toBeInTheDocument()
  })

  it("applies custom className", () => {
    render(
      <Pagination
        onLoadMore={() => {}}
        hasMore={true}
        isLoading={false}
        className="custom-class"
      />
    )
    const container = screen.getByRole("button").parentElement
    expect(container).toHaveClass("custom-class")
  })

  it("handles zero items displayed", () => {
    render(
      <Pagination
        onLoadMore={() => {}}
        hasMore={true}
        isLoading={false}
        itemCount={0}
        totalCount={100}
      />
    )
    expect(screen.getByText("0 of 100")).toBeInTheDocument()
  })

  it("has correct aria-label for loading state", () => {
    render(
      <Pagination
        onLoadMore={() => {}}
        hasMore={true}
        isLoading={true}
      />
    )
    expect(screen.getByRole("button")).toHaveAttribute("aria-label", "Loading more items")
  })

  it("has correct aria-label for ready state", () => {
    render(
      <Pagination
        onLoadMore={() => {}}
        hasMore={true}
        isLoading={false}
      />
    )
    expect(screen.getByRole("button")).toHaveAttribute("aria-label", "Load more items")
  })
})
