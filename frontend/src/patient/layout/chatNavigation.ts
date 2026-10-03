import { createContext, useContext } from 'react';
import type { ChatSession } from '../../types/agent';

export interface ChatNavigation {
  sessions: ChatSession[];
  currentSessionId: string;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  busy: boolean;
}
export const ChatNavigationContext = createContext<(navigation: ChatNavigation | null) => void>(() => undefined);
export function useRegisterChatNavigation() { return useContext(ChatNavigationContext); }
