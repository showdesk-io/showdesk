import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge, PriorityBadge } from "../StatusBadge";

describe("StatusBadge", () => {
  it("renders open status", () => {
    render(<StatusBadge status="open" />);
    expect(screen.getByText("open")).toBeInTheDocument();
  });

  it("renders in_progress as 'in progress'", () => {
    render(<StatusBadge status="in_progress" />);
    expect(screen.getByText("in progress")).toBeInTheDocument();
  });

  it("renders resolved status", () => {
    render(<StatusBadge status="resolved" />);
    expect(screen.getByText("resolved")).toBeInTheDocument();
  });

  it("renders closed status", () => {
    render(<StatusBadge status="closed" />);
    expect(screen.getByText("closed")).toBeInTheDocument();
  });

  it("renders waiting status", () => {
    render(<StatusBadge status="waiting" />);
    expect(screen.getByText("waiting")).toBeInTheDocument();
  });

  it("applies correct CSS class for each status", () => {
    const { container } = render(<StatusBadge status="open" />);
    const badge = container.querySelector("span");
    expect(badge?.className).toContain("bg-blue-100");
  });
});

describe("PriorityBadge", () => {
  it("renders low priority", () => {
    render(<PriorityBadge priority="low" />);
    expect(screen.getByText("low")).toBeInTheDocument();
  });

  it("renders medium priority", () => {
    render(<PriorityBadge priority="medium" />);
    expect(screen.getByText("medium")).toBeInTheDocument();
  });

  it("renders high priority", () => {
    render(<PriorityBadge priority="high" />);
    expect(screen.getByText("high")).toBeInTheDocument();
  });

  it("renders urgent priority", () => {
    render(<PriorityBadge priority="urgent" />);
    expect(screen.getByText("urgent")).toBeInTheDocument();
  });

  it("applies correct CSS class for urgent", () => {
    const { container } = render(<PriorityBadge priority="urgent" />);
    const badge = container.querySelector("span");
    expect(badge?.className).toContain("bg-red-100");
  });
});
