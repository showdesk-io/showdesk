/**
 * Type declaration for the Showdesk widget global, loaded via /cdn/widget.js.
 */

export interface ShowdeskUser {
  id?: string;
  name?: string;
  email?: string;
  hash?: string;
}

export interface ShowdeskInitConfig {
  token: string;
  apiUrl?: string;
  position?: "bottom-right" | "bottom-left";
  color?: string;
  label?: string;
  greeting?: string;
  hideButton?: boolean;
  navigationMode?: "spa" | "mpa";
  user?: ShowdeskUser;
}

export interface ShowdeskGlobal {
  init(config: ShowdeskInitConfig): void;
  open(): void;
  destroy(): void;
  reset(): void;
  setUser(user: ShowdeskUser): void;
}

declare global {
  interface Window {
    Showdesk?: ShowdeskGlobal;
  }
}

export {};
