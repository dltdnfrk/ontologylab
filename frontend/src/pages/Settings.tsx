import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Cpu,
  ExternalLink,
  KeyRound,
  Loader2,
  Network,
  Newspaper,
  Power,
  RotateCcw,
  Save,
  StickyNote,
} from "lucide-react";
import { get, post } from "@/lib/api";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";

// ---------------------------------------------------------------------------
// API types
// ---------------------------------------------------------------------------

interface SettingsData {
  default_engine: string;
  default_model: string | null;
  chunk_size: number;
  api_keys: Record<string, string>;
  disabled_sources: string[];
  searxng_url: string | null;
  data_dir: string | null;
  packs_dir: string | null;
}

interface EngineInfo {
  name: string;
  available: boolean;
  default_model: string | null;
  models: string[];
}

interface PaperSource {
  id: string;
  label: string;
  keyed: boolean;
  connectable: boolean;
  key_present: boolean;
  available: boolean;
}

interface PaperSourcesResponse {
  sources: PaperSource[];
  default: string;
}

interface SchemaType {
  name: string;
  description: string;
}

interface ActiveSchema {
  label: string;
  description: string;
  entity_types: SchemaType[];
  relation_types: SchemaType[];
}

interface SchemaPreset {
  name: string;
  label: string;
  description: string;
  entity_types: number;
  relation_types: number;
}

interface SchemaResponse {
  active: ActiveSchema | null;
  presets: SchemaPreset[];
}

interface Annotation {
  id: string;
  node_name: string;
  node_type: string;
  resource: string;
  external_id: string;
  record_url: string;
  matched_name: string;
  status: string;
  created_ts: number;
}

interface AnnotationsResponse {
  annotations: Annotation[];
  resources: { id: string; label: string }[];
}

type Section = "settings" | "sources" | "schema" | "annotations";

type BadgeVariant = "default" | "secondary" | "destructive" | "outline";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DEFAULT_CHUNK_SIZE = 1024;

function normalizeSettings(raw: Partial<SettingsData>): SettingsData {
  return {
    default_engine: raw.default_engine ?? "",
    default_model: raw.default_model ?? null,
    chunk_size: raw.chunk_size ?? DEFAULT_CHUNK_SIZE,
    api_keys: raw.api_keys ?? {},
    disabled_sources: raw.disabled_sources ?? [],
    searxng_url: raw.searxng_url ?? null,
    data_dir: raw.data_dir ?? null,
    packs_dir: raw.packs_dir ?? null,
  };
}

function buildPayload(settings: SettingsData): SettingsData {
  return {
    ...settings,
    api_keys: Object.fromEntries(
      Object.entries(settings.api_keys).filter(([, value]) => value.trim() !== "")
    ),
  };
}

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function formatTs(ts: number): string {
  return new Date(ts * 1000).toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const ANNOTATION_STATUS: Record<string, { label: string; variant: BadgeVariant }> = {
  proposed: { label: "대기", variant: "secondary" },
  verified: { label: "확인", variant: "default" },
  rejected: { label: "거부", variant: "destructive" },
};

const RECENT_ANNOTATION_LIMIT = 10;
const ENTITY_TYPE_BADGE_LIMIT = 8;

// ---------------------------------------------------------------------------
// Section placeholders
// ---------------------------------------------------------------------------

function SectionSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-4 w-72" />
      </CardHeader>
      <CardContent className="space-y-3">
        {Array.from({ length: rows }).map((_, i) => (
          <Skeleton key={i} className="h-9 w-full" />
        ))}
      </CardContent>
    </Card>
  );
}

function SectionError({
  title,
  message,
  busy,
  onRetry,
}: {
  title: string;
  message: string;
  busy: boolean;
  onRetry: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Alert variant="destructive">
          <AlertCircle />
          <AlertTitle>불러오기 실패</AlertTitle>
          <AlertDescription>{message}</AlertDescription>
        </Alert>
        <Button variant="outline" size="sm" onClick={onRetry} disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : <RotateCcw />}
          다시 시도
        </Button>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SettingsPage() {
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<Partial<Record<Section, boolean>>>({});
  const [errors, setErrors] = useState<Partial<Record<Section, string>>>({});

  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [engines, setEngines] = useState<EngineInfo[]>([]);
  const [enginesError, setEnginesError] = useState<string | null>(null);
  const [sources, setSources] = useState<PaperSourcesResponse | null>(null);
  const [schema, setSchema] = useState<SchemaResponse | null>(null);
  const [annotations, setAnnotations] = useState<AnnotationsResponse | null>(null);

  const [saving, setSaving] = useState(false);
  const [formMessage, setFormMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [sourceMessage, setSourceMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);

  const [selectedPreset, setSelectedPreset] = useState("");
  const [switching, setSwitching] = useState(false);
  const [schemaMessage, setSchemaMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const setBusyKey = (key: Section, value: boolean) =>
    setBusy((prev) => ({ ...prev, [key]: value }));
  const setErrorKey = (key: Section, message: string | null) =>
    setErrors((prev) => ({ ...prev, [key]: message ?? undefined }));

  const loadSettings = useCallback(async () => {
    setBusyKey("settings", true);
    try {
      const raw = await get<Partial<SettingsData>>("/settings");
      setSettings(normalizeSettings(raw));
      setErrorKey("settings", null);
    } catch (e) {
      setErrorKey("settings", errText(e));
    } finally {
      setBusyKey("settings", false);
    }
  }, []);

  const loadEngines = useCallback(async () => {
    try {
      setEngines(await get<EngineInfo[]>("/engines"));
      setEnginesError(null);
    } catch (e) {
      setEnginesError(errText(e));
    }
  }, []);

  const loadSources = useCallback(async () => {
    setBusyKey("sources", true);
    try {
      setSources(await get<PaperSourcesResponse>("/paper-sources"));
      setErrorKey("sources", null);
    } catch (e) {
      setErrorKey("sources", errText(e));
    } finally {
      setBusyKey("sources", false);
    }
  }, []);

  const loadSchema = useCallback(async () => {
    setBusyKey("schema", true);
    try {
      setSchema(await get<SchemaResponse>("/schema"));
      setErrorKey("schema", null);
    } catch (e) {
      setErrorKey("schema", errText(e));
    } finally {
      setBusyKey("schema", false);
    }
  }, []);

  const loadAnnotations = useCallback(async () => {
    setBusyKey("annotations", true);
    try {
      setAnnotations(await get<AnnotationsResponse>("/annotations"));
      setErrorKey("annotations", null);
    } catch (e) {
      setErrorKey("annotations", errText(e));
    } finally {
      setBusyKey("annotations", false);
    }
  }, []);

  useEffect(() => {
    void Promise.all([loadSettings(), loadEngines(), loadSources(), loadSchema(), loadAnnotations()]).finally(
      () => setLoading(false)
    );
  }, [loadSettings, loadEngines, loadSources, loadSchema, loadAnnotations]);

  const updateSettings = (patch: Partial<SettingsData>) => {
    setSettings((prev) => (prev ? { ...prev, ...patch } : prev));
    setFormMessage(null);
  };

  const saveSettings = async () => {
    if (!settings) return;
    setSaving(true);
    setFormMessage(null);
    try {
      await post("/settings", buildPayload(settings));
      setFormMessage({ ok: true, text: "설정을 저장했습니다." });
    } catch (e) {
      setFormMessage({ ok: false, text: `저장에 실패했습니다: ${errText(e)}` });
    } finally {
      setSaving(false);
    }
  };

  const toggleSource = async (sourceId: string) => {
    if (!settings || toggling) return;
    const previous = settings;
    const disabled = new Set(settings.disabled_sources);
    if (disabled.has(sourceId)) {
      disabled.delete(sourceId);
    } else {
      disabled.add(sourceId);
    }
    const next = { ...settings, disabled_sources: [...disabled] };
    setSettings(next);
    setToggling(sourceId);
    setSourceMessage(null);
    try {
      await post("/settings", buildPayload(next));
    } catch (e) {
      setSettings(previous);
      setSourceMessage({ ok: false, text: `소스 상태 변경에 실패했습니다: ${errText(e)}` });
    } finally {
      setToggling(null);
    }
  };

  const applyPreset = async () => {
    if (!selectedPreset || switching) return;
    setSwitching(true);
    setSchemaMessage(null);
    try {
      await post("/schema", { preset: selectedPreset });
      await loadSchema();
      setSchemaMessage({ ok: true, text: "온톨로지를 전환했습니다." });
      setSelectedPreset("");
    } catch (e) {
      setSchemaMessage({ ok: false, text: `온톨로지 전환에 실패했습니다: ${errText(e)}` });
    } finally {
      setSwitching(false);
    }
  };

  // -------------------------------------------------------------------------
  // Derived view data
  // -------------------------------------------------------------------------

  const selectedEngine = engines.find((e) => e.name === settings?.default_engine);
  const engineOptions: EngineInfo[] =
    settings && settings.default_engine && !engines.some((e) => e.name === settings.default_engine)
      ? [{ name: settings.default_engine, available: true, default_model: null, models: [] }, ...engines]
      : engines;

  const connectableSources = sources?.sources.filter((s) => s.connectable) ?? [];
  const disabledSources = new Set(settings?.disabled_sources ?? []);

  const recentAnnotations = [...(annotations?.annotations ?? [])]
    .sort((a, b) => b.created_ts - a.created_ts)
    .slice(0, RECENT_ANNOTATION_LIMIT);
  const resourceLabel = (id: string) =>
    annotations?.resources.find((r) => r.id === id)?.label ?? id;

  const saveDisabled =
    saving || !settings || settings.default_engine === "" || settings.chunk_size < 1;

  // -------------------------------------------------------------------------
  // Sections
  // -------------------------------------------------------------------------

  const renderGeneralSection = () => {
    if (errors.settings) {
      return (
        <SectionError
          title="일반 설정"
          message={errors.settings}
          busy={!!busy.settings}
          onRetry={() => void loadSettings()}
        />
      );
    }
    if (!settings) return null;
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Cpu className="h-5 w-5" />
            일반 설정
          </CardTitle>
          <CardDescription>추출과 검토에 사용할 기본 엔진, 모델, 청크 크기를 설정합니다.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {enginesError && (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertTitle>엔진 목록을 불러오지 못했습니다</AlertTitle>
              <AlertDescription>{enginesError}</AlertDescription>
            </Alert>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="default-engine" className="text-sm font-medium">
                기본 엔진
              </label>
              <Select
                value={settings.default_engine || undefined}
                onValueChange={(value) => {
                  const engine = engines.find((e) => e.name === value);
                  updateSettings({
                    default_engine: value,
                    default_model:
                      engine && engine.models.length > 0
                        ? engine.default_model ?? engine.models[0]
                        : null,
                  });
                }}
              >
                <SelectTrigger id="default-engine">
                  <SelectValue placeholder="엔진 선택" />
                </SelectTrigger>
                <SelectContent>
                  {engineOptions.map((engine) => (
                    <SelectItem key={engine.name} value={engine.name} disabled={!engine.available}>
                      {engine.name}
                      {!engine.available ? " — 사용 불가" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="default-model" className="text-sm font-medium">
                기본 모델
              </label>
              {selectedEngine && selectedEngine.models.length > 0 ? (
                <Select
                  value={settings.default_model ?? undefined}
                  onValueChange={(value) => updateSettings({ default_model: value })}
                >
                  <SelectTrigger id="default-model">
                    <SelectValue placeholder="모델 선택" />
                  </SelectTrigger>
                  <SelectContent>
                    {selectedEngine.models.map((model) => (
                      <SelectItem key={model} value={model}>
                        {model}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  id="default-model"
                  value={settings.default_model ?? ""}
                  placeholder="엔진 기본값 사용"
                  onChange={(e) => updateSettings({ default_model: e.target.value || null })}
                />
              )}
            </div>
            <div className="space-y-1.5">
              <label htmlFor="chunk-size" className="text-sm font-medium">
                청크 크기
              </label>
              <Input
                id="chunk-size"
                type="number"
                min={1}
                step={1}
                value={settings.chunk_size}
                onChange={(e) => {
                  const n = Number.parseInt(e.target.value, 10);
                  updateSettings({ chunk_size: Number.isNaN(n) ? 0 : n });
                }}
              />
              {settings.chunk_size < 1 ? (
                <p className="text-xs text-destructive">1 이상의 값을 입력하세요.</p>
              ) : (
                <p className="text-xs text-muted-foreground">추출 시 문서를 나누는 기본 크기입니다.</p>
              )}
            </div>
          </div>
          {connectableSources.length > 0 && (
            <>
              <Separator />
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <KeyRound className="h-4 w-4" />
                  논문 소스 API 키
                </div>
                <p className="text-sm text-muted-foreground">
                  소스별 API 키를 등록하면 더 높은 요청 한도를 사용할 수 있습니다.
                </p>
                <div className="grid gap-4 sm:grid-cols-2">
                  {connectableSources.map((source) => (
                    <div key={source.id} className="space-y-1.5">
                      <div className="flex items-center gap-2">
                        <label htmlFor={`api-key-${source.id}`} className="text-sm font-medium">
                          {source.label}
                        </label>
                        {source.key_present && <Badge variant="secondary">등록됨</Badge>}
                      </div>
                      <Input
                        id={`api-key-${source.id}`}
                        type="password"
                        autoComplete="off"
                        placeholder="API 키 입력"
                        value={settings.api_keys[source.id] ?? ""}
                        onChange={(e) =>
                          updateSettings({
                            api_keys: { ...settings.api_keys, [source.id]: e.target.value },
                          })
                        }
                      />
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
          {formMessage && (
            <Alert variant={formMessage.ok ? "default" : "destructive"}>
              {formMessage.ok ? <CheckCircle2 /> : <AlertCircle />}
              <AlertDescription>{formMessage.text}</AlertDescription>
            </Alert>
          )}
        </CardContent>
        <CardFooter className="justify-end">
          <Button onClick={() => void saveSettings()} disabled={saveDisabled}>
            {saving ? <Loader2 className="animate-spin" /> : <Save />}
            저장
          </Button>
        </CardFooter>
      </Card>
    );
  };

  const renderSourcesSection = () => {
    if (errors.sources) {
      return (
        <SectionError
          title="논문 소스"
          message={errors.sources}
          busy={!!busy.sources}
          onRetry={() => void loadSources()}
        />
      );
    }
    if (!sources) return null;
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Newspaper className="h-5 w-5" />
            논문 소스
          </CardTitle>
          <CardDescription>
            논문을 가져올 소스를 관리합니다. 비활성화된 소스는 수집 시 제외되며 변경 사항은 즉시 저장됩니다.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {sourceMessage && (
            <Alert variant={sourceMessage.ok ? "default" : "destructive"}>
              {sourceMessage.ok ? <CheckCircle2 /> : <AlertCircle />}
              <AlertDescription>{sourceMessage.text}</AlertDescription>
            </Alert>
          )}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>소스</TableHead>
                <TableHead>상태</TableHead>
                <TableHead className="text-right">사용 여부</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sources.sources.map((source) => {
                const enabled = !disabledSources.has(source.id);
                return (
                  <TableRow key={source.id}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{source.label}</span>
                        {source.id === sources.default && <Badge>기본</Badge>}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {source.available ? (
                          <Badge variant="secondary">사용 가능</Badge>
                        ) : (
                          <Badge variant="destructive">사용 불가</Badge>
                        )}
                        {source.keyed && !source.key_present && <Badge variant="outline">키 필요</Badge>}
                        {source.key_present && <Badge variant="outline">키 등록됨</Badge>}
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant={enabled ? "outline" : "default"}
                        disabled={!settings || toggling !== null}
                        onClick={() => void toggleSource(source.id)}
                      >
                        {toggling === source.id ? (
                          <Loader2 className="animate-spin" />
                        ) : (
                          <Power />
                        )}
                        {enabled ? "비활성화" : "활성화"}
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    );
  };

  const renderSchemaSection = () => {
    if (errors.schema) {
      return (
        <SectionError
          title="온톨로지"
          message={errors.schema}
          busy={!!busy.schema}
          onRetry={() => void loadSchema()}
        />
      );
    }
    if (!schema) return null;
    const active = schema.active;
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Network className="h-5 w-5" />
            온톨로지
          </CardTitle>
          <CardDescription>추출에 사용할 온톨로지를 확인하고 전환합니다.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {active ? (
            <div className="space-y-2 rounded-lg border bg-muted/50 p-4">
              <div className="flex items-center gap-2">
                <span className="font-medium">{active.label}</span>
                <Badge>활성</Badge>
              </div>
              {active.description && (
                <p className="text-sm text-muted-foreground">{active.description}</p>
              )}
              <div className="flex flex-wrap gap-1">
                <Badge variant="secondary">엔티티 타입 {active.entity_types.length}개</Badge>
                <Badge variant="secondary">관계 타입 {active.relation_types.length}개</Badge>
              </div>
              {active.entity_types.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {active.entity_types.slice(0, ENTITY_TYPE_BADGE_LIMIT).map((type) => (
                    <Badge key={type.name} variant="outline">
                      {type.name}
                    </Badge>
                  ))}
                  {active.entity_types.length > ENTITY_TYPE_BADGE_LIMIT && (
                    <Badge variant="outline">+{active.entity_types.length - ENTITY_TYPE_BADGE_LIMIT}</Badge>
                  )}
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">활성 온톨로지가 없습니다.</p>
          )}
          <Separator />
          <div className="space-y-2">
            <label htmlFor="schema-preset" className="text-sm font-medium">
              온톨로지 전환
            </label>
            <div className="flex gap-2">
              <Select value={selectedPreset || undefined} onValueChange={setSelectedPreset}>
                <SelectTrigger id="schema-preset" className="flex-1">
                  <SelectValue placeholder="프리셋 선택" />
                </SelectTrigger>
                <SelectContent>
                  {schema.presets.map((preset) => (
                    <SelectItem key={preset.name} value={preset.name}>
                      {preset.label} (엔티티 {preset.entity_types} / 관계 {preset.relation_types})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button onClick={() => void applyPreset()} disabled={!selectedPreset || switching}>
                {switching ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}
                적용
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              새 온톨로지를 적용하면 이전 온톨로지는 비활성화되며, 기존 검토 대기 항목은 유지됩니다.
            </p>
          </div>
          {schemaMessage && (
            <Alert variant={schemaMessage.ok ? "default" : "destructive"}>
              {schemaMessage.ok ? <CheckCircle2 /> : <AlertCircle />}
              <AlertDescription>{schemaMessage.text}</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>
    );
  };

  const renderAnnotationsSection = () => {
    if (errors.annotations) {
      return (
        <SectionError
          title="최근 주석"
          message={errors.annotations}
          busy={!!busy.annotations}
          onRetry={() => void loadAnnotations()}
        />
      );
    }
    if (!annotations) return null;
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <StickyNote className="h-5 w-5" />
            최근 주석
          </CardTitle>
          <CardDescription>외부 리소스와 매칭된 최근 주석입니다.</CardDescription>
        </CardHeader>
        <CardContent>
          {recentAnnotations.length === 0 ? (
            <p className="text-sm text-muted-foreground">표시할 주석이 없습니다.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>노드</TableHead>
                  <TableHead>리소스</TableHead>
                  <TableHead>외부 ID</TableHead>
                  <TableHead>일치 이름</TableHead>
                  <TableHead>상태</TableHead>
                  <TableHead>생성일</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentAnnotations.map((annotation) => {
                  const status = ANNOTATION_STATUS[annotation.status] ?? {
                    label: annotation.status,
                    variant: "outline" as BadgeVariant,
                  };
                  return (
                    <TableRow key={annotation.id}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{annotation.node_name}</span>
                          <Badge variant="outline">{annotation.node_type}</Badge>
                        </div>
                      </TableCell>
                      <TableCell>{resourceLabel(annotation.resource)}</TableCell>
                      <TableCell>
                        {annotation.record_url ? (
                          <a
                            href={annotation.record_url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 underline-offset-4 hover:underline"
                          >
                            {annotation.external_id}
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        ) : (
                          annotation.external_id
                        )}
                      </TableCell>
                      <TableCell>{annotation.matched_name}</TableCell>
                      <TableCell>
                        <Badge variant={status.variant}>{status.label}</Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap">{formatTs(annotation.created_ts)}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    );
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold">설정</h1>
        <p className="text-muted-foreground">
          추출 엔진, 논문 소스, 온톨로지 등 애플리케이션 설정을 관리합니다.
        </p>
      </div>
      {loading ? (
        <>
          <SectionSkeleton rows={4} />
          <SectionSkeleton rows={3} />
          <SectionSkeleton rows={3} />
          <SectionSkeleton rows={5} />
        </>
      ) : (
        <>
          {renderGeneralSection()}
          {renderSourcesSection()}
          {renderSchemaSection()}
          {renderAnnotationsSection()}
        </>
      )}
    </div>
  );
}
