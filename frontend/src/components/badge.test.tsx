import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { Badge } from "@beadhub/dashboard/components/ui"

describe("Badge component", () => {
  it("renders with default variant", () => {
    render(<Badge>Test Badge</Badge>)
    expect(screen.getByText("Test Badge")).toBeInTheDocument()
  })

  it("renders with secondary variant", () => {
    render(<Badge variant="secondary">Secondary</Badge>)
    const badge = screen.getByText("Secondary")
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveClass("bg-secondary")
  })

  it("renders with warning variant", () => {
    render(<Badge variant="warning">Warning</Badge>)
    const badge = screen.getByText("Warning")
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveClass("bg-warning")
  })

  it("applies custom className", () => {
    render(<Badge className="custom-class">Custom</Badge>)
    const badge = screen.getByText("Custom")
    expect(badge).toHaveClass("custom-class")
  })
})
