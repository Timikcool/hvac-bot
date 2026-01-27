export interface EquipmentContext {
  brand?: string;
  model?: string;
  serial?: string;
  systemType?: string;
}

export interface Citation {
  sourceNumber: number;
  title?: string;
  manual?: string;  // deprecated, use title
  page?: number[];
  section?: string;
  documentId?: string;
  manualId?: string;  // deprecated, use documentId
  documentType?: string;
}

export type MessageRole = 'user' | 'assistant' | 'system';
export type ConfidenceLevel = 'high' | 'medium' | 'low' | 'none';

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  citations?: Citation[];
  safetyWarnings?: string[];
  confidence?: ConfidenceLevel;
  requiresEscalation?: boolean;
  suggestedFollowups?: string[];
  timestamp: Date;
  imageUrl?: string;
  responseTimeMs?: number;
  userRating?: number;
}

export interface ChatRequest {
  message: string;
  equipment?: EquipmentContext;
  conversationId?: string;
  includeImages?: boolean;
}

export interface ChatResponse {
  answer: string;
  confidence: ConfidenceLevel;
  citations: Citation[];
  safetyWarnings: string[];
  suggestedFollowups: string[];
  requiresEscalation: boolean;
  conversationId: string;
  messageId: string;
  responseTimeMs: number;
}

export interface EquipmentScanResponse {
  brand: string;
  model: string;
  serial: string;
  manufactureDate: string;
  specs: Record<string, string>;
  confidence: number;
  manualsAvailable: string[];
}

export interface VisibleIssue {
  description: string;
  evidence?: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
}

export interface ManualReference {
  content: string;
  source?: string;
  page?: number[];
  relevance: number;
}

export interface DiagnosisResponse {
  identifiedComponents: string[];
  visibleIssues: VisibleIssue[];
  suggestedCauses: string[];
  recommendedChecks: string[];
  manualReferences: {
    issue: string;
    references: ManualReference[];
  }[];
  confidence: number;
  requiresPhysicalInspection: boolean;
}

export interface Manual {
  id: string;
  title: string;
  brand: string;
  model?: string;
  systemType?: string;
  pageCount: number;
}

// Speech Recognition types for browsers
declare global {
  interface Window {
    SpeechRecognition: typeof SpeechRecognition;
    webkitSpeechRecognition: typeof SpeechRecognition;
    webkitSpeechGrammarList: typeof SpeechGrammarList;
  }
}
