import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { GettingStartedPage } from "@/pages/GettingStartedPage"

describe("GettingStartedPage", () => {
  it("renders the primary init command", () => {
    render(<GettingStartedPage />)
    expect(screen.getByText("bdh :init")).toBeInTheDocument()
  })
})

