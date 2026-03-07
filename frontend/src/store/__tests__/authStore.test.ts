import { describe, it, expect, beforeEach } from "vitest";
import { useAuthStore } from "../authStore";

describe("authStore", () => {
  beforeEach(() => {
    // Reset store between tests
    useAuthStore.setState({
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
    });
  });

  it("starts unauthenticated", () => {
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.accessToken).toBeNull();
    expect(state.refreshToken).toBeNull();
  });

  it("setTokens sets auth state", () => {
    useAuthStore.getState().setTokens("access-123", "refresh-456");
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.accessToken).toBe("access-123");
    expect(state.refreshToken).toBe("refresh-456");
  });

  it("logout clears auth state", () => {
    useAuthStore.getState().setTokens("access-123", "refresh-456");
    useAuthStore.getState().logout();
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.accessToken).toBeNull();
    expect(state.refreshToken).toBeNull();
  });

  it("setTokens can be called multiple times", () => {
    useAuthStore.getState().setTokens("old-access", "old-refresh");
    useAuthStore.getState().setTokens("new-access", "new-refresh");
    const state = useAuthStore.getState();
    expect(state.accessToken).toBe("new-access");
    expect(state.refreshToken).toBe("new-refresh");
  });
});
