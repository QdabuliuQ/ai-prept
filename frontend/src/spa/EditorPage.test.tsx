import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EditorPage from "./EditorPage";

const { appShellMock } = vi.hoisted(() => ({
  appShellMock: vi.fn(),
}));

vi.mock("@/app-shell", () => ({
  default: appShellMock,
}));

describe("EditorPage", () => {
  beforeEach(() => {
    appShellMock.mockReset();
    appShellMock.mockImplementation(() => (
      <div data-testid="app-shell">App shell</div>
    ));
  });

  it("renders the application shell", () => {
    render(<EditorPage />);

    expect(screen.getByTestId("app-shell").textContent).toBe("App shell");
    expect(appShellMock).toHaveBeenCalledTimes(1);
    expect(appShellMock).toHaveBeenCalledWith({}, undefined);
  });

  it("renders the application shell without adding extra page markup", () => {
    const { container } = render(<EditorPage />);

    expect(container.firstElementChild).toHaveAttribute("data-testid", "app-shell");
    expect(container.children).toHaveLength(1);
    expect(appShellMock).toHaveBeenCalledTimes(1);
  });

  it("renders again when the page is rerendered", () => {
    const { rerender } = render(<EditorPage />);

    rerender(<EditorPage />);

    expect(appShellMock).toHaveBeenCalledTimes(2);
  });

  it("propagates an AppShell rendering error", () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    appShellMock.mockImplementationOnce(() => {
      throw new Error("AppShell failed to render");
    });

    expect(() => render(<EditorPage />)).toThrow("AppShell failed to render");

    consoleError.mockRestore();
  });

  it("propagates errors thrown by AppShell on a later render", () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    appShellMock
      .mockImplementationOnce(() => <div data-testid="app-shell">Ready</div>)
      .mockImplementationOnce(() => {
        throw new Error("AppShell failed after rerender");
      });

    const { rerender } = render(<EditorPage />);

    expect(() => rerender(<EditorPage />)).toThrow(
      "AppShell failed after rerender",
    );

    consoleError.mockRestore();
  });
});
