import type { components } from './schema'
import { type ApiTransport, type HttpMethod, toApiError } from './transport'

type S = components['schemas']
export type Health = S['HealthOut']
export type SystemInfo = S['SystemInfoOut']
export type Subject = S['SubjectOut']
export type SubjectDetail = S['SubjectDetailOut']
export type SubjectIn = S['SubjectIn']
export type SubjectPatch = S['SubjectPatch']
export type Unit = S['UnitOut']
export type UnitIn = S['UnitIn']
export type UnitPatch = S['UnitPatch']
export type Session = S['SessionOut']
export type SessionIn = S['SessionIn']
export type Source = S['SourceOut']
export type SourceList = S['SourceListOut']
export type SourcePatch = S['SourcePatch']
export type SourceContent = S['SourceContentOut']
export type TextSourceIn = S['TextSourceIn']
export type Job = S['JobOut']
export type SttStatus = S['SttStatusOut']
export type SttModel = S['ModelOut']
export type SttLanguage = SttStatus['language']
export type ExportFile = S['ExportOut']
export type SourceAudio = S['AudioOut']
export type AudioKeepDays = SttStatus['audio_keep_days']
export type AiStatus = S['AiStatusOut']
export type KeepAlive = AiStatus['keep_alive']
export type GeneratedDoc = S['DocOut']
export type GeneratedDocDetail = S['DocDetailOut']
export type DocIn = S['DocIn']
export type DocKind = GeneratedDoc['kind']
export type DocDetail = GeneratedDoc['detail']
export type DocCitation = S['CitationOut']
export type ChatThread = S['ThreadOut']
export type ChatThreadDetail = S['ThreadDetailOut']
export type ChatMessage = S['MessageOut']
export type ChatScope = S['Scope']
export type RagStatus = S['RagStatusOut']
export type SourceIndex = S['SourceIndexOut']
export type Exam = S['ExamOut']
export type ExamIn = S['ExamIn']
export type ExamConfig = S['ExamConfig']
export type Deck = S['DeckOut']
export type DeckDetail = S['DeckDetailOut']
export type DeckIn = S['DeckIn']
export type Flashcard = S['CardOut']
export type CardPatch = S['CardPatch']
export type Study = S['StudyOut']
export type Rating = S['ReviewIn']['rating']
export type Stats = S['StatsOut']
export type Attempt = S['AttemptOut']
export type AttemptQuestion = S['QuestionOut']
export type AnswerState = S['AnswerStateOut']
export type AnswerIn = S['AnswerIn']
export type WeakTopic = S['WeakTopicOut']
export type CloudStatus = S['CloudStatusOut']
export type CloudSettingsIn = S['CloudSettingsIn']
export type CloudPreviewIn = S['PreviewIn']
export type CloudPreview = S['PreviewOut']
export type CloudConsent = S['ConsentOut']
export type CloudRequest = S['CloudRequestOut']
export type CloudKind = CloudPreviewIn['kind']
export type CloudTask = 'chat' | 'docs' | 'generate' | 'review'
/** Petición de vista previa: solo `kind` es obligatorio (el resto tiene valor por defecto). */
export type CloudAsk = Pick<CloudPreviewIn, 'kind'> & Partial<CloudPreviewIn>
export type SourceKind = Source['kind']
export type SourceStatus = Source['status']

export interface SourceFilters {
  subject_id?: string
  unit_id?: string
  kind?: SourceKind
  status?: SourceStatus
  q?: string
  limit?: number
  offset?: number
}

/** Construye la query sin valores vacíos (encodeURIComponent evita inyectar parámetros). */
function query(params: object): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
  return parts.length ? `?${parts.join('&')}` : ''
}

const id = (value: string) => encodeURIComponent(value)

/** Cliente tipado de la API. Los tipos se generan desde OpenAPI (`npm run gen:api`). */
export class ApiClient {
  private readonly transport: ApiTransport

  constructor(transport: ApiTransport) {
    this.transport = transport
  }

  private async call<T>(method: HttpMethod, path: string, body?: unknown): Promise<T> {
    const res = await this.transport.request(method, path, body)
    if (res.status < 200 || res.status >= 300) throw toApiError(res)
    return res.body as T
  }

  health(): Promise<Health> {
    return this.call('GET', '/api/v1/health')
  }

  systemInfo(): Promise<SystemInfo> {
    return this.call('GET', '/api/v1/system/info')
  }

  // --- Asignaturas, unidades y sesiones
  listSubjects(archived = false): Promise<Subject[]> {
    return this.call('GET', `/api/v1/subjects${query({ archived })}`)
  }
  getSubject(subjectId: string): Promise<SubjectDetail> {
    return this.call('GET', `/api/v1/subjects/${id(subjectId)}`)
  }
  createSubject(body: SubjectIn): Promise<Subject> {
    return this.call('POST', '/api/v1/subjects', body)
  }
  updateSubject(subjectId: string, body: SubjectPatch): Promise<Subject> {
    return this.call('PATCH', `/api/v1/subjects/${id(subjectId)}`, body)
  }
  deleteSubject(subjectId: string): Promise<void> {
    return this.call('DELETE', `/api/v1/subjects/${id(subjectId)}`)
  }
  createUnit(subjectId: string, body: UnitIn): Promise<Unit> {
    return this.call('POST', `/api/v1/subjects/${id(subjectId)}/units`, body)
  }
  updateUnit(unitId: string, body: UnitPatch): Promise<Unit> {
    return this.call('PATCH', `/api/v1/units/${id(unitId)}`, body)
  }
  deleteUnit(unitId: string): Promise<void> {
    return this.call('DELETE', `/api/v1/units/${id(unitId)}`)
  }
  createSession(subjectId: string, body: SessionIn): Promise<Session> {
    return this.call('POST', `/api/v1/subjects/${id(subjectId)}/sessions`, body)
  }
  deleteSession(sessionId: string): Promise<void> {
    return this.call('DELETE', `/api/v1/sessions/${id(sessionId)}`)
  }

  // --- Fuentes (biblioteca)
  listSources(filters: SourceFilters = {}): Promise<SourceList> {
    return this.call('GET', `/api/v1/sources${query(filters)}`)
  }
  getSource(sourceId: string): Promise<Source> {
    return this.call('GET', `/api/v1/sources/${id(sourceId)}`)
  }
  createTextSource(body: TextSourceIn): Promise<Source> {
    return this.call('POST', '/api/v1/sources/text', body)
  }
  updateSource(sourceId: string, body: SourcePatch): Promise<Source> {
    return this.call('PATCH', `/api/v1/sources/${id(sourceId)}`, body)
  }
  deleteSource(sourceId: string): Promise<void> {
    return this.call('DELETE', `/api/v1/sources/${id(sourceId)}`)
  }
  getContent(sourceId: string, version?: number): Promise<SourceContent> {
    return this.call('GET', `/api/v1/sources/${id(sourceId)}/content${query({ version })}`)
  }
  saveContent(sourceId: string, text: string, baseVersion: number): Promise<SourceContent> {
    return this.call('PUT', `/api/v1/sources/${id(sourceId)}/content`, {
      text,
      base_version: baseVersion,
    })
  }
  retrySource(sourceId: string): Promise<Source> {
    return this.call('POST', `/api/v1/sources/${id(sourceId)}/retry`)
  }

  // --- Transcripción
  sttStatus(): Promise<SttStatus> {
    return this.call('GET', '/api/v1/stt')
  }
  updateSttSettings(body: {
    model?: string
    language?: SttLanguage
    audio_keep_days?: AudioKeepDays
  }): Promise<SttStatus> {
    return this.call('PUT', '/api/v1/stt/settings', body)
  }
  downloadModel(modelId: string): Promise<SttStatus> {
    return this.call('POST', `/api/v1/stt/models/${id(modelId)}/download`)
  }
  transcribe(sourceId: string, language?: SttLanguage): Promise<Source> {
    return this.call('POST', `/api/v1/sources/${id(sourceId)}/transcribe`, { language })
  }
  sourceAudio(sourceId: string): Promise<SourceAudio> {
    return this.call('GET', `/api/v1/sources/${id(sourceId)}/audio`)
  }
  deleteSourceAudio(sourceId: string): Promise<SourceAudio> {
    return this.call('DELETE', `/api/v1/sources/${id(sourceId)}/audio`)
  }
  exportSource(sourceId: string, format: 'txt' | 'srt'): Promise<ExportFile> {
    return this.call('GET', `/api/v1/sources/${id(sourceId)}/export${query({ format })}`)
  }

  // --- IA local: apuntes y resúmenes
  aiStatus(): Promise<AiStatus> {
    return this.call('GET', '/api/v1/ai/status')
  }
  updateAiSettings(body: { model?: string; keep_alive?: KeepAlive }): Promise<AiStatus> {
    return this.call('PUT', '/api/v1/ai/settings', body)
  }
  listDocuments(subjectId: string): Promise<GeneratedDoc[]> {
    return this.call('GET', `/api/v1/subjects/${id(subjectId)}/documents`)
  }
  createDocument(subjectId: string, body: DocIn): Promise<GeneratedDoc> {
    return this.call('POST', `/api/v1/subjects/${id(subjectId)}/documents`, body)
  }
  getDocument(docId: string): Promise<GeneratedDocDetail> {
    return this.call('GET', `/api/v1/documents/${id(docId)}`)
  }
  retryDocument(docId: string): Promise<GeneratedDoc> {
    return this.call('POST', `/api/v1/documents/${id(docId)}/retry`)
  }
  deleteDocument(docId: string): Promise<void> {
    return this.call('DELETE', `/api/v1/documents/${id(docId)}`)
  }

  // --- Asistente (búsqueda en tus fuentes)
  listThreads(): Promise<ChatThread[]> {
    return this.call('GET', '/api/v1/chat/threads')
  }
  createThread(scope: ChatScope, title?: string): Promise<ChatThread> {
    return this.call('POST', '/api/v1/chat/threads', { scope, title })
  }
  getThread(threadId: string): Promise<ChatThreadDetail> {
    return this.call('GET', `/api/v1/chat/threads/${id(threadId)}`)
  }
  updateThread(threadId: string, body: { title?: string; scope?: ChatScope }): Promise<ChatThread> {
    return this.call('PATCH', `/api/v1/chat/threads/${id(threadId)}`, body)
  }
  deleteThread(threadId: string): Promise<void> {
    return this.call('DELETE', `/api/v1/chat/threads/${id(threadId)}`)
  }
  ask(threadId: string, text: string, consentId?: string | null): Promise<ChatMessage> {
    return this.call('POST', `/api/v1/chat/threads/${id(threadId)}/messages`, {
      text,
      consent_id: consentId ?? null,
    })
  }
  getMessage(messageId: string): Promise<ChatMessage> {
    return this.call('GET', `/api/v1/chat/messages/${id(messageId)}`)
  }
  cancelMessage(messageId: string): Promise<ChatMessage> {
    return this.call('POST', `/api/v1/chat/messages/${id(messageId)}/cancel`)
  }
  ragStatus(): Promise<RagStatus> {
    return this.call('GET', '/api/v1/rag/status')
  }
  sourceIndex(sourceId: string): Promise<SourceIndex> {
    return this.call('GET', `/api/v1/sources/${id(sourceId)}/index`)
  }

  // --- Exámenes
  listExams(subjectId: string): Promise<Exam[]> {
    return this.call('GET', `/api/v1/subjects/${id(subjectId)}/exams`)
  }
  createExam(subjectId: string, body: ExamIn): Promise<Exam> {
    return this.call('POST', `/api/v1/subjects/${id(subjectId)}/exams`, body)
  }
  getExam(examId: string): Promise<Exam> {
    return this.call('GET', `/api/v1/exams/${id(examId)}`)
  }
  acceptExam(examId: string): Promise<Exam> {
    return this.call('POST', `/api/v1/exams/${id(examId)}/accept`)
  }
  retryExam(examId: string): Promise<Exam> {
    return this.call('POST', `/api/v1/exams/${id(examId)}/retry`)
  }
  deleteExam(examId: string): Promise<void> {
    return this.call('DELETE', `/api/v1/exams/${id(examId)}`)
  }
  startAttempt(examId: string): Promise<Attempt> {
    return this.call('POST', `/api/v1/exams/${id(examId)}/attempts`)
  }
  getAttempt(attemptId: string): Promise<Attempt> {
    return this.call('GET', `/api/v1/attempts/${id(attemptId)}`)
  }
  saveAnswer(attemptId: string, questionId: string, body: AnswerIn): Promise<AnswerState> {
    return this.call('PUT', `/api/v1/attempts/${id(attemptId)}/answers/${id(questionId)}`, body)
  }
  checkAnswer(attemptId: string, questionId: string): Promise<AnswerState> {
    return this.call('POST', `/api/v1/attempts/${id(attemptId)}/answers/${id(questionId)}/check`)
  }
  submitAttempt(attemptId: string): Promise<Attempt> {
    return this.call('POST', `/api/v1/attempts/${id(attemptId)}/submit`)
  }
  deleteAttempt(attemptId: string): Promise<void> {
    return this.call('DELETE', `/api/v1/attempts/${id(attemptId)}`)
  }

  // --- Claude en la nube (Fase 8)
  cloudStatus(refresh = false): Promise<CloudStatus> {
    return this.call(
      'GET',
      `/api/v1/cloud/status${query({ refresh: refresh ? 'true' : undefined })}`,
    )
  }
  updateCloudSettings(body: CloudSettingsIn): Promise<CloudStatus> {
    return this.call('PUT', '/api/v1/cloud/settings', body)
  }
  setCloudApiKey(key: string): Promise<CloudStatus> {
    return this.call('PUT', '/api/v1/cloud/api-key', { key })
  }
  deleteCloudApiKey(): Promise<CloudStatus> {
    return this.call('DELETE', '/api/v1/cloud/api-key')
  }
  cloudPreview(body: CloudAsk): Promise<CloudPreview> {
    return this.call('POST', '/api/v1/cloud/preview', body)
  }
  giveCloudConsent(body: CloudAsk & { mode: 'once' | 'session' }): Promise<CloudConsent> {
    return this.call('POST', '/api/v1/cloud/consents', body)
  }
  revokeSessionConsents(): Promise<void> {
    return this.call('DELETE', '/api/v1/cloud/consents')
  }
  cloudRequests(limit = 50): Promise<CloudRequest[]> {
    return this.call('GET', `/api/v1/cloud/requests${query({ limit })}`)
  }

  // --- Flashcards y repaso
  listDecks(subjectId: string): Promise<Deck[]> {
    return this.call('GET', `/api/v1/subjects/${id(subjectId)}/decks`)
  }
  createDeck(subjectId: string, body: DeckIn): Promise<Deck> {
    return this.call('POST', `/api/v1/subjects/${id(subjectId)}/decks`, body)
  }
  getDeck(deckId: string): Promise<DeckDetail> {
    return this.call('GET', `/api/v1/decks/${id(deckId)}`)
  }
  retryDeck(deckId: string): Promise<Deck> {
    return this.call('POST', `/api/v1/decks/${id(deckId)}/retry`)
  }
  deleteDeck(deckId: string): Promise<void> {
    return this.call('DELETE', `/api/v1/decks/${id(deckId)}`)
  }
  updateCard(cardId: string, body: CardPatch): Promise<Flashcard> {
    return this.call('PATCH', `/api/v1/cards/${id(cardId)}`, body)
  }
  deleteCard(cardId: string): Promise<void> {
    return this.call('DELETE', `/api/v1/cards/${id(cardId)}`)
  }
  study(scope: { subject_id?: string; deck_id?: string }): Promise<Study> {
    return this.call('GET', `/api/v1/study${query(scope)}`)
  }
  reviewCard(cardId: string, rating: Rating, durationMs: number): Promise<Flashcard> {
    return this.call('POST', `/api/v1/cards/${id(cardId)}/review`, {
      rating,
      duration_ms: durationMs,
    })
  }
  updateStudySettings(body: { new_per_day: number }): Promise<Study> {
    return this.call('PUT', '/api/v1/study/settings', body)
  }
  stats(params: { subject_id?: string; days?: number }): Promise<Stats> {
    return this.call('GET', `/api/v1/stats${query(params)}`)
  }

  // --- Trabajos en segundo plano
  listJobs(active = true): Promise<Job[]> {
    return this.call('GET', `/api/v1/jobs${query({ active, limit: 50 })}`)
  }
  cancelJob(jobId: string): Promise<Job> {
    return this.call('POST', `/api/v1/jobs/${id(jobId)}/cancel`)
  }
}
