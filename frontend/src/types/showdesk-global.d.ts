/**
 * Type declaration for the Showdesk widget global, loaded via /cdn/widget.js.
 */

export interface ShowdeskUser {
  id?: string | number;
  name?: string;
  email?: string;
  hash?: string;
  emailHash?: string;
  traits?: Record<string, unknown>;
}

export interface ShowdeskCompany {
  id: string | number;
  name: string;
  domain?: string;
  traits?: Record<string, unknown>;
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
  company?: ShowdeskCompany;
}

export interface ShowdeskGlobal {
  init(config: ShowdeskInitConfig): void;
  open(): void;
  destroy(): void;
  reset(): void;
  setUser(user?: ShowdeskUser | null, company?: ShowdeskCompany): void;
}

declare global {
  interface Window {
    Showdesk?: ShowdeskGlobal;
  }
}

export {};
