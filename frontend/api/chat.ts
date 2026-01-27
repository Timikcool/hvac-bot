import {
  ChatRequest,
  ChatResponse,
  EquipmentContext,
  EquipmentScanResponse,
  DiagnosisResponse,
  Manual,
} from '@/types';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Debug logging helper
const DEBUG = process.env.NODE_ENV === 'development';

function log(category: string, message: string, data?: unknown) {
  if (DEBUG) {
    const timestamp = new Date().toISOString().slice(11, 23);
    console.log(`[${timestamp}] [API:${category}] ${message}`, data ?? '');
  }
}

function logError(category: string, message: string, error: unknown) {
  const timestamp = new Date().toISOString().slice(11, 23);
  console.error(`[${timestamp}] [API:${category}] ERROR: ${message}`, error);
}

class ChatApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
    log('init', `ChatApiClient initialized with baseUrl: ${baseUrl}`);
  }

  async sendMessage(request: ChatRequest): Promise<ChatResponse> {
    log('chat', 'Sending message', {
      messageLength: request.message.length,
      hasEquipment: !!request.equipment,
      conversationId: request.conversationId,
    });

    const startTime = performance.now();

    const response = await fetch(`${this.baseUrl}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message: request.message,
        equipment: request.equipment
          ? {
              brand: request.equipment.brand,
              model: request.equipment.model,
              serial: request.equipment.serial,
              system_type: request.equipment.systemType,
            }
          : null,
        conversation_id: request.conversationId,
        include_images: request.includeImages ?? false,
      }),
    });

    const duration = Math.round(performance.now() - startTime);

    if (!response.ok) {
      logError('chat', `Request failed with status ${response.status}`, await response.text());
      throw new Error(`Chat API error: ${response.status}`);
    }

    const data = await response.json();

    log('chat', `Response received in ${duration}ms`, {
      confidence: data.confidence,
      citationsCount: data.citations?.length ?? 0,
      requiresEscalation: data.requires_escalation,
      answerLength: data.answer?.length ?? 0,
    });

    // Map citations from snake_case to camelCase
    const citations = (data.citations || []).map((c: Record<string, unknown>) => ({
      sourceNumber: c.source_number,
      title: c.title,
      manual: c.manual || c.title,  // backward compat
      page: c.page,
      section: c.section,
      documentId: c.document_id,
      documentType: c.document_type,
    }));

    return {
      answer: data.answer,
      confidence: data.confidence,
      citations,
      safetyWarnings: data.safety_warnings,
      suggestedFollowups: data.suggested_followups,
      requiresEscalation: data.requires_escalation,
      conversationId: data.conversation_id,
    };
  }

  async scanEquipment(imageBlob: Blob): Promise<EquipmentScanResponse> {
    log('scan', 'Scanning equipment nameplate', { imageSize: imageBlob.size });

    const formData = new FormData();
    formData.append('image', imageBlob, 'nameplate.jpg');

    const startTime = performance.now();
    const response = await fetch(`${this.baseUrl}/api/scan-equipment`, {
      method: 'POST',
      body: formData,
    });
    const duration = Math.round(performance.now() - startTime);

    if (!response.ok) {
      logError('scan', `Scan failed with status ${response.status}`, await response.text());
      throw new Error(`Equipment scan error: ${response.status}`);
    }

    const data = await response.json();

    log('scan', `Equipment identified in ${duration}ms`, {
      brand: data.brand,
      model: data.model,
      confidence: data.confidence,
    });

    return {
      brand: data.brand,
      model: data.model,
      serial: data.serial,
      manufactureDate: data.manufacture_date,
      specs: data.specs,
      confidence: data.confidence,
      manualsAvailable: data.manuals_available,
    };
  }

  async analyzeImage(
    imageBlob: Blob,
    description: string,
    equipment?: EquipmentContext | null
  ): Promise<DiagnosisResponse> {
    log('analyze', 'Analyzing problem image', {
      imageSize: imageBlob.size,
      descriptionLength: description.length,
      hasEquipment: !!equipment,
    });

    const formData = new FormData();
    formData.append('image', imageBlob, 'problem.jpg');
    formData.append('description', description);

    if (equipment?.brand) {
      formData.append('equipment_brand', equipment.brand);
    }
    if (equipment?.model) {
      formData.append('equipment_model', equipment.model);
    }

    const startTime = performance.now();
    const response = await fetch(`${this.baseUrl}/api/analyze-image`, {
      method: 'POST',
      body: formData,
    });
    const duration = Math.round(performance.now() - startTime);

    if (!response.ok) {
      logError('analyze', `Analysis failed with status ${response.status}`, await response.text());
      throw new Error(`Image analysis error: ${response.status}`);
    }

    const data = await response.json();

    log('analyze', `Analysis complete in ${duration}ms`, {
      issuesFound: data.visible_issues?.length ?? 0,
      confidence: data.confidence,
      requiresInspection: data.requires_physical_inspection,
    });

    return {
      identifiedComponents: data.identified_components,
      visibleIssues: data.visible_issues,
      suggestedCauses: data.suggested_causes,
      recommendedChecks: data.recommended_checks,
      manualReferences: data.manual_references,
      confidence: data.confidence,
      requiresPhysicalInspection: data.requires_physical_inspection,
    };
  }

  async listManuals(filters?: {
    brand?: string;
    model?: string;
    systemType?: string;
  }): Promise<Manual[]> {
    const params = new URLSearchParams();
    if (filters?.brand) params.append('brand', filters.brand);
    if (filters?.model) params.append('model', filters.model);
    if (filters?.systemType) params.append('system_type', filters.systemType);

    const response = await fetch(
      `${this.baseUrl}/api/manuals?${params.toString()}`
    );

    if (!response.ok) {
      throw new Error(`Manuals list error: ${response.status}`);
    }

    return response.json();
  }

  async getManualPage(
    manualId: string,
    pageNumber: number
  ): Promise<Blob> {
    const response = await fetch(
      `${this.baseUrl}/api/manuals/${manualId}/page/${pageNumber}`
    );

    if (!response.ok) {
      throw new Error(`Manual page error: ${response.status}`);
    }

    return response.blob();
  }

  async submitFeedback(
    conversationId: string,
    messageId: string,
    feedbackType: 'helpful' | 'incorrect' | 'incomplete',
    details?: string
  ): Promise<void> {
    const formData = new FormData();
    formData.append('conversation_id', conversationId);
    formData.append('message_id', messageId);
    formData.append('feedback_type', feedbackType);
    if (details) {
      formData.append('details', details);
    }

    const response = await fetch(`${this.baseUrl}/api/feedback`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Feedback submission error: ${response.status}`);
    }
  }

  async healthCheck(): Promise<boolean> {
    try {
      const response = await fetch(`${this.baseUrl}/health`);
      return response.ok;
    } catch {
      return false;
    }
  }
}

export const chatApi = new ChatApiClient();
