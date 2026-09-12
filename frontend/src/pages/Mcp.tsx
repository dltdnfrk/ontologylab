import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  Copy,
  FolderTree,
  Loader2,
  Package,
  Plug,
  PlugZap,
  Power,
  RefreshCw,
  Server,
  Terminal,
  Wrench,
} from "lucide-react";
import { get, post } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

/* ---------------------------------------------------------------------------
 * API shapes
 *
 * `/api/mcp/status` currently answers with the pack roster the stdio server can
 * serve ({packs_dir, packs, count, unusable}). A build that owns a long-lived
 * server instead answers with {running, connected_pack, tool_count}. Both are
 * accepted here so the screen stays truthful against either backend rather than
 * inventing a state it cannot observe.
 * ------------------------------------------------------------------------- */

type PackCounts = Record<string, number | undefined>;

type StdioConfig = {
  command?: string;
  args?: string[];
};

type McpPackEntry = {
  pack_id: string;
  counts?: PackCounts | null;
  created_ts?: string | number | null;
  serve_command?: string;
  stdio_config?: StdioConfig;
};

type UnusablePack = {
  pack_dir?: string;
  reason?: string;
};

type McpStatus = {
  packs_dir?: string;
  packs?: McpPackEntry[];
  count?: number;
  unusable?: UnusablePack[];
  running?: boolean;
  connected_pack?: string | null;
  pack_id?: string | null;
  tool_count?: number;
};

type PackSummary = {
  pack_id: string;
  counts?: PackCounts | null;
  created_ts?: string | number | null;
};

type PacksResponse = {
  packs?: PackSummary[];
  count?: number;
  unusable?: UnusablePack[];
};

type McpTool = {
  name: string;
  description?: string | null;
  title?: string | null;
};

type ToolsResponse = {
  tools?: McpTool[];
  count?: number;
};

type ServerState = "running" | "ready" | "stopped" | "empty";

type Notice = {
  kind: "success" | "info" | "error";
  text: string;
};

/* ---------------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------------- */

const CLAUDE_CONFIG_PATH_MAC =
  "~/Library/Application Support/Claude/claude_desktop_config.json";
const CLAUDE_CONFIG_PATH_WIN = "%APPDATA%\\Claude\\claude_desktop_config.json";

/** The api client throws `Error("<status>: <body>")`; recover that status. */
function httpStatusOf(error: unknown): number | null {
  if (!(error instanceof Error)) return null;
  const match = /^(\d{3}):/.exec(error.message);
  return match ? Number(match[1]) : null;
}

function errorText(error: unknown, fallback: string): string {
  if (!(error instanceof Error)) return fallback;
  const status = httpStatusOf(error);
  const detail = status
    ? error.message.slice(String(status).length + 1).trim()
    : error.message;
  return detail ? `${fallback} (${detail})` : fallback;
}

/** True when the backend simply does not expose the route we just called. */
function isUnsupportedRoute(error: unknown): boolean {
  const status = httpStatusOf(error);
  return status === 404 || status === 405 || status === 501;
}

function formatTimestamp(ts?: string | number | null): string {
  if (ts === null || ts === undefined || ts === "") return "—";
  const raw = typeof ts === "number" ? ts : Number(ts);
  const date = Number.isFinite(raw)
    ? new Date(raw < 1e12 ? raw * 1000 : raw)
    : new Date(String(ts));
  if (Number.isNaN(date.getTime())) return String(ts);
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function countsLabel(counts?: PackCounts | null): string {
  const c = counts ?? {};
  return `문서 ${c.documents ?? 0} · 개념 ${c.nodes_verified ?? 0} · 관계 ${
    c.edges_verified ?? 0
  }`;
}

/** Copy through the async clipboard, falling back for non-secure contexts. */
async function writeClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Permission or insecure-context refusal — the legacy path below is the
      // handling, not a swallowed failure.
    }
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

/* ---------------------------------------------------------------------------
 * Small presentational pieces, composed from the same tokens as the primitives
 * ------------------------------------------------------------------------- */

function Stat({
  icon: Icon,
  label,
  children,
}: {
  icon: typeof Server;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border bg-muted/40 p-4">
      <div className="flex items-center gap-2 text-label font-medium tracking-label text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        <span>{label}</span>
      </div>
      <div className="mt-2 text-sm font-medium">{children}</div>
    </div>
  );
}

function CopyButton({
  value,
  label,
  copiedKey,
  onCopied,
  itemKey,
  className,
}: {
  value: string;
  label: string;
  copiedKey: string | null;
  onCopied: (key: string | null) => void;
  itemKey: string;
  className?: string;
}) {
  const copied = copiedKey === itemKey;
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className={className}
      onClick={async () => {
        const ok = await writeClipboard(value);
        onCopied(ok ? itemKey : null);
        if (ok) window.setTimeout(() => onCopied(null), 1600);
      }}
    >
      {copied ? <Check /> : <Copy />}
      {copied ? "복사됨!" : label}
    </Button>
  );
}

function MachineValue({ children }: { children: React.ReactNode }) {
  return (
    <code className="block break-all rounded-md bg-muted px-2 py-1 font-mono text-xs text-foreground">
      {children}
    </code>
  );
}

/* ---------------------------------------------------------------------------
 * Page
 * ------------------------------------------------------------------------- */

export default function McpPage() {
  const [status, setStatus] = useState<McpStatus | null>(null);
  const [packs, setPacks] = useState<PackSummary[]>([]);
  const [tools, setTools] = useState<McpTool[] | null>(null);
  const [toolsNote, setToolsNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [toolsLoading, setToolsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState<"connect" | "disconnect" | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setToolsLoading(true);
    setError(null);

    const [statusResult, packsResult] = await Promise.allSettled([
      get<McpStatus>("/mcp/status"),
      get<PacksResponse>("/packs"),
    ]);

    if (statusResult.status === "fulfilled") {
      setStatus(statusResult.value ?? null);
    } else {
      setStatus(null);
      setError(errorText(statusResult.reason, "MCP 상태를 불러오지 못했습니다."));
    }

    if (packsResult.status === "fulfilled") {
      setPacks(packsResult.value?.packs ?? []);
    } else {
      setPacks([]);
      setError((prev) =>
        prev ?? errorText(packsResult.reason, "팩 목록을 불러오지 못했습니다.")
      );
    }
    setLoading(false);

    try {
      const payload = await get<ToolsResponse | McpTool[]>("/mcp/tools");
      const list = Array.isArray(payload) ? payload : payload?.tools ?? [];
      setTools(list);
      setToolsNote(null);
    } catch (toolsError) {
      setTools(null);
      setToolsNote(
        isUnsupportedRoute(toolsError)
          ? "이 서버는 도구 목록 API를 제공하지 않습니다. 팩을 연결하면 Claude가 도구 목록을 직접 보여줍니다."
          : errorText(toolsError, "도구 목록을 불러오지 못했습니다.")
      );
    } finally {
      setToolsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const statusEntries = useMemo(() => status?.packs ?? [], [status]);

  const connectedPackId = useMemo(
    () => status?.connected_pack ?? status?.pack_id ?? null,
    [status]
  );

  /** Prefer the live pack roster; fall back to /api/packs when it is empty. */
  const options = useMemo<PackSummary[]>(
    () => (statusEntries.length > 0 ? statusEntries : packs),
    [statusEntries, packs]
  );

  useEffect(() => {
    if (options.length === 0) {
      setSelected("");
      return;
    }
    setSelected((prev) => {
      if (prev && options.some((pack) => pack.pack_id === prev)) return prev;
      if (
        connectedPackId &&
        options.some((pack) => pack.pack_id === connectedPackId)
      ) {
        return connectedPackId;
      }
      return options[0].pack_id;
    });
  }, [options, connectedPackId]);

  const serverState = useMemo<ServerState>(() => {
    if (typeof status?.running === "boolean") {
      return status.running ? "running" : "stopped";
    }
    if (connectedPackId) return "running";
    return options.length > 0 ? "ready" : "empty";
  }, [status, connectedPackId, options.length]);

  const selectedEntry = useMemo(
    () => statusEntries.find((entry) => entry.pack_id === selected) ?? null,
    [statusEntries, selected]
  );

  const selectedPack = useMemo(
    () => options.find((pack) => pack.pack_id === selected) ?? null,
    [options, selected]
  );

  const configJson = useMemo(() => {
    if (!selectedEntry?.stdio_config) return null;
    return JSON.stringify(
      {
        mcpServers: {
          [`ontologylab-${selectedEntry.pack_id}`]: selectedEntry.stdio_config,
        },
      },
      null,
      2
    );
  }, [selectedEntry]);

  const toolCount = status?.tool_count ?? tools?.length ?? null;
  const unusable = status?.unusable ?? [];

  const runAction = useCallback(
    async (action: "connect" | "disconnect") => {
      if (action === "connect" && !selected) return;
      setBusy(action);
      setNotice(null);
      try {
        if (action === "connect") {
          await post("/mcp/connect", { pack_id: selected });
          setNotice({
            kind: "success",
            text: `'${selected}' 팩을 MCP 서버에 연결했습니다.`,
          });
        } else {
          await post("/mcp/disconnect");
          setNotice({ kind: "success", text: "MCP 서버 연결을 해제했습니다." });
        }
        await load();
      } catch (actionError) {
        setNotice(
          isUnsupportedRoute(actionError)
            ? {
                kind: "info",
                text: "이 서버는 대시보드에서의 연결 전환을 지원하지 않습니다. MCP 서버는 Claude Desktop이 직접 실행하므로, 아래 연결 설정을 복사해 붙여넣으세요.",
              }
            : {
                kind: "error",
                text: errorText(
                  actionError,
                  action === "connect"
                    ? "연결에 실패했습니다."
                    : "연결 해제에 실패했습니다."
                ),
              }
        );
      } finally {
        setBusy(null);
      }
    },
    [selected, load]
  );

  // 서버 수명주기는 판정(초록·호박·진홍)이 아니다 — '진행 중'의 자리를 쓴다.
  const stateBadge: Record<
    ServerState,
    { label: string; variant: "running" | "secondary" | "outline" }
  > = {
    running: { label: "실행 중", variant: "running" },
    ready: { label: "연결 준비됨", variant: "secondary" },
    stopped: { label: "중지됨", variant: "outline" },
    empty: { label: "팩 없음", variant: "outline" },
  };

  return (
    <div className="mx-auto w-full max-w-[var(--content-max)] space-y-6 p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight">연결</h1>
          <p className="text-sm text-muted-foreground">
            지식 팩을 Claude에 연결합니다 · 인공지능은 팩을 읽기만 합니다
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => void load()}
          disabled={loading}
        >
          <RefreshCw className={cn(loading && "animate-spin")} />
          새로고침
        </Button>
      </header>

      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>불러오기 실패</AlertTitle>
          <AlertDescription>
            {error} — 서버가 실행 중인지 확인한 뒤 새로고침하세요.
          </AlertDescription>
        </Alert>
      )}

      {/* 1. MCP 서버 상태 */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div className="space-y-1.5">
            <CardTitle className="flex items-center gap-2">
              <Server className="h-4 w-4" />
              MCP 서버 상태
            </CardTitle>
            <CardDescription>
              팩 하나를 읽기 전용으로 Claude에 노출합니다
            </CardDescription>
          </div>
          {loading ? (
            <Skeleton className="h-6 w-20" />
          ) : (
            <Badge variant={stateBadge[serverState].variant}>
              {stateBadge[serverState].label}
            </Badge>
          )}
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-[5.5rem] w-full" />
              ))}
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Stat icon={Plug} label="상태">
                {stateBadge[serverState].label}
              </Stat>
              <Stat icon={Package} label="연결된 팩">
                {connectedPackId ? (
                  <span className="font-mono text-xs">{connectedPackId}</span>
                ) : (
                  <span className="text-muted-foreground">연결 안 됨</span>
                )}
              </Stat>
              <Stat icon={Wrench} label="도구">
                {toolCount === null ? (
                  <span className="text-muted-foreground">—</span>
                ) : (
                  `${toolCount}개`
                )}
              </Stat>
              <Stat icon={FolderTree} label="팩 디렉터리">
                {status?.packs_dir ? (
                  <span
                    className="block break-all font-mono text-xs"
                    title={status.packs_dir}
                  >
                    {status.packs_dir}
                  </span>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </Stat>
            </div>
          )}
        </CardContent>
      </Card>

      {unusable.length > 0 && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>열 수 없는 팩 폴더 {unusable.length}개</AlertTitle>
          <AlertDescription>
            <p className="text-muted-foreground">
              다음 폴더는 팩으로 읽을 수 없어 목록에서 제외했습니다.
            </p>
            <ul className="mt-2 space-y-1">
              {unusable.map((item, index) => (
                <li key={item.pack_dir ?? index} className="text-xs">
                  <span className="font-mono">{item.pack_dir ?? "—"}</span>
                  <span className="text-muted-foreground">
                    {" "}
                    — {item.reason ?? "알 수 없는 이유"}
                  </span>
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {/* 2 + 3. 팩 선택과 연결 제어 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <PlugZap className="h-4 w-4" />
            팩 연결
          </CardTitle>
          <CardDescription>
            Claude에 노출할 팩을 고른 뒤 연결합니다
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {loading ? (
            <div className="space-y-4">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-64" />
            </div>
          ) : options.length === 0 ? (
            <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
              연결할 팩이 없습니다. 먼저 <strong>팩</strong> 화면에서 팩을
              빌드하세요.
            </p>
          ) : (
            <>
              <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                <div className="space-y-2">
                  <label
                    className="text-sm font-medium"
                    htmlFor="mcp-pack-select"
                  >
                    팩 선택
                  </label>
                  <Select value={selected} onValueChange={setSelected}>
                    <SelectTrigger id="mcp-pack-select" aria-label="팩 선택">
                      <SelectValue placeholder="팩을 선택하세요" />
                    </SelectTrigger>
                    <SelectContent>
                      {options.map((pack) => (
                        <SelectItem key={pack.pack_id} value={pack.pack_id}>
                          {pack.pack_id}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    onClick={() => void runAction("connect")}
                    disabled={!selected || busy !== null}
                  >
                    {busy === "connect" ? (
                      <Loader2 className="animate-spin" />
                    ) : (
                      <Plug />
                    )}
                    연결
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => void runAction("disconnect")}
                    disabled={busy !== null}
                  >
                    {busy === "disconnect" ? (
                      <Loader2 className="animate-spin" />
                    ) : (
                      <Power />
                    )}
                    연결 해제
                  </Button>
                </div>
              </div>

              {selectedPack && (
                <div className="rounded-lg border bg-muted/40 p-4 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono text-xs font-medium">
                      {selectedPack.pack_id}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {formatTimestamp(selectedPack.created_ts)}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {countsLabel(selectedPack.counts)}
                  </p>
                  {selectedEntry?.serve_command && (
                    <div className="mt-3 space-y-1.5">
                      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <Terminal className="h-3.5 w-3.5" />
                        실행 명령
                      </p>
                      <MachineValue>{selectedEntry.serve_command}</MachineValue>
                    </div>
                  )}
                </div>
              )}

              {notice && (
                <Alert
                  variant={
                    notice.kind === "error"
                      ? "destructive"
                      : notice.kind === "success"
                        ? "success"
                        : "warning"
                  }
                >
                  {notice.kind === "success" ? (
                    <Check className="h-4 w-4" />
                  ) : (
                    <AlertTriangle className="h-4 w-4" />
                  )}
                  <AlertTitle>
                    {notice.kind === "success"
                      ? "완료"
                      : notice.kind === "info"
                        ? "안내"
                        : "실패"}
                  </AlertTitle>
                  <AlertDescription>{notice.text}</AlertDescription>
                </Alert>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* 4. 사용 가능한 도구 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Wrench className="h-4 w-4" />
            사용 가능한 도구
            {tools && tools.length > 0 && (
              <Badge variant="secondary">{tools.length}</Badge>
            )}
          </CardTitle>
          <CardDescription>
            연결된 팩에 대해 Claude가 호출할 수 있는 읽기 전용 도구입니다
          </CardDescription>
        </CardHeader>
        <CardContent>
          {toolsLoading ? (
            <div className="space-y-2">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-9 w-full" />
              ))}
            </div>
          ) : tools && tools.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[16rem]">이름</TableHead>
                  <TableHead>설명</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tools.map((tool) => (
                  <TableRow key={tool.name}>
                    <TableCell className="font-mono text-xs font-medium">
                      {tool.name}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {tool.description ?? tool.title ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
              {toolsNote ?? "표시할 도구가 없습니다."}
            </p>
          )}
        </CardContent>
      </Card>

      {/* 5. Claude Desktop 연결 방법 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Terminal className="h-4 w-4" />
            Claude Desktop에 붙여넣는 방법
          </CardTitle>
          <CardDescription>
            설정 파일에 아래 내용을 넣고 Claude Desktop을 재시작합니다
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <ol className="list-decimal space-y-2 pl-5 text-sm">
            <li>
              아래 <strong>연결 설정 복사 (JSON)</strong>를 클릭합니다.
            </li>
            <li>
              Claude Desktop → 설정 → 개발자 → <strong>설정 편집</strong>으로
              설정 파일을 엽니다.
            </li>
            <li>
              <code className="font-mono text-xs">mcpServers</code> 항목 안에
              붙여넣고 저장합니다.
            </li>
            <li>
              Claude Desktop을 재시작한 뒤, 대화에서 팩 내용을 물어보면
              확인됩니다.
            </li>
          </ol>

          <div className="space-y-2">
            <p className="text-label font-medium tracking-label text-muted-foreground">
              설정 파일 경로
            </p>
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <span className="w-16 shrink-0 text-xs text-muted-foreground">
                  macOS
                </span>
                <MachineValue>{CLAUDE_CONFIG_PATH_MAC}</MachineValue>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-16 shrink-0 text-xs text-muted-foreground">
                  Windows
                </span>
                <MachineValue>{CLAUDE_CONFIG_PATH_WIN}</MachineValue>
              </div>
            </div>
          </div>

          {configJson ? (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-label font-medium tracking-label text-muted-foreground">
                  연결 설정 (
                  <span className="font-mono">{selectedEntry?.pack_id}</span>)
                </p>
                <CopyButton
                  value={configJson}
                  label="연결 설정 복사 (JSON)"
                  itemKey="config"
                  copiedKey={copiedKey}
                  onCopied={setCopiedKey}
                />
              </div>
              <pre className="overflow-x-auto rounded-lg border bg-muted p-4 font-mono text-xs leading-relaxed">
                {configJson}
              </pre>
            </div>
          ) : (
            <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
              {loading
                ? "연결 설정을 불러오는 중입니다…"
                : "선택한 팩의 연결 설정을 서버가 제공하지 않았습니다. 팩을 빌드한 뒤 새로고침하세요."}
            </p>
          )}

          {status?.packs_dir && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-4">
              <p className="text-xs text-muted-foreground">
                팩 디렉터리 전체 경로가 필요하면 복사하세요.
              </p>
              <CopyButton
                value={status.packs_dir}
                label="팩 디렉터리 복사"
                itemKey="packs-dir"
                copiedKey={copiedKey}
                onCopied={setCopiedKey}
              />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
