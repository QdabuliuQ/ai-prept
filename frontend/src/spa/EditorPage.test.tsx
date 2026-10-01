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
});
