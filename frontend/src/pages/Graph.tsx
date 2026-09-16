import * as React from "react";
import {
  AlertTriangle,
  Crosshair,
  Eye,
  EyeOff,
  Loader2,
  MousePointer2,
  Network,
  RefreshCw,
  Search,
  Share2,
  X,
} from "lucide-react";
import Graph from "graphology";
import Sigma from "sigma";
import type { NodeDisplayData } from "sigma/types";
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
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { get } from "@/lib/api";
import { cn } from "@/lib/utils";
import NodeStatusProgram from "@/lib/graphNodeProgram";

/* ==========================================================================
   자유 탐색용 지식그래프 화면.

   읽기 전용이다 — 승인/거부는 검토 화면의 게이트에서만 일어난다(HITL 불변식).
   여기서 하는 일은 "무엇이 있고 무엇이 아직 사람 눈을 기다리는지"를 한 화면에
   보여 주는 것까지다.

   렌더러는 sigma.js(WebGL) + graphology. SVG DOM 이었던 구 구현보다 큰
   그래프에서 훨씬 가볍다. 레이아웃 물리는 검증된 기존 힘 시뮬레이션을 그대로
   쓰고, 매 프레임 좌표만 graphology 노드 속성으로 흘려 sigma가 그린다.

   두 개의 색 축을 쓴다. 섞으면 화면이 거짓말을 한다:
     · 채움(fill)  = 엔티티 타입  → --chart-1..5 순환
     · 링(stroke)  = 검토 상태    → 실선 초록(승인) / 점선 호박(대기)
   선택은 '상호작용 상태'라 '데이터 상태'를 덮지 않는다 — 상태 링은 그대로
   두고 바깥에 --point 후광만 덧댄다. 둘 다 NodeStatusProgram 한 프로그램이
   그린다.

   캔버스 위 세 가지 상호작용은 이름 있는 액션이다 — 노드 선택(selectNode),
   상세 보기(inspectNode), 이웃 펼치기(expandNeighbors). 클릭·더블클릭·키보드
   모두 같은 액션을 호출하고, 선택 카드의 버튼으로도 명시적으로 실행할 수 있다.
   ========================================================================== */

type EntityStatus = "proposed" | "verified" | "rejected";

interface ApiNode {
  id: string;
  entity_type: string;
  name: string;
  aliases: string[];
  properties: Record<string, unknown>;
  status: EntityStatus;
  confidence: number | null;
  source_doc_id: string | null;
  /** neighbors 응답에만 있는 BFS 깊이. */
  hop?: number;
}

interface ApiEdge {
  id: string;
  relation_type: string;
  source_id: string;
  target_id: string;
  status: EntityStatus;
  confidence: number | null;
}

interface GraphPayload {
  nodes: ApiNode[];
  edges: ApiEdge[];
}

interface SearchHit {
  id: string;
  name: string;
  entity_type: string;
  status: EntityStatus;
  score: number | null;
}

interface SearchPayload {
  results: SearchHit[];
}

interface EntityRelation {
  id: string;
  relation_type: string;
  direction: "in" | "out";
  other: { id: string; name: string; status: EntityStatus };
  status: EntityStatus;
  confidence: number | null;
  critic_score: number | null;
}

interface EntityMention {
  source_doc_id: string;
  doc_title: string | null;
  excerpt: string;
}

interface EntityDetail {
  entity: ApiNode;
  critic: { engine: string; model: string | null; score: number; rationale: string | null } | null;
  mentions: EntityMention[];
  relations: EntityRelation[];
  counts: {
    mentions: number;
    relations_proposed: number;
    relations_verified: number;
    merge_candidates: number;
  };
}

/* ---------- 시뮬레이션 상태 ---------- */

interface SimNode {
  id: string;
  name: string;
  entityType: string;
  status: EntityStatus;
  confidence: number | null;
  x: number;
  y: number;
  vx: number;
  vy: number;
  /** 드래그로 고정된 좌표. null 이면 힘이 지배한다. */
  fx: number | null;
  fy: number | null;
}

interface SimEdge {
  id: string;
  source: string;
  target: string;
  relationType: string;
  status: EntityStatus;
}

interface Size {
  w: number;
  h: number;
}

/* ---------- 상수 ----------
   물리 값은 구 구현(web/app.js)에서 그대로 가져왔다. 노드 200개 스코프에서
   실제로 가라앉는 것이 확인된 조합이라, 임의로 바꾸면 배치가 진동한다. */

const NODE_LIMIT = 200;
const REPULSION = 1400;
const REPULSION_CUTOFF = 160_000; /* 400px 밖은 무시 */
const SPRING_LENGTH = 90;
const SPRING_K = 0.02;
const GRAVITY = 0.002;
const DAMPING = 0.85;
const ALPHA_DECAY = 0.985;
const ALPHA_MIN = 0.02;
const LABEL_BASE_PX = 11; /* --fs-label */
const TYPE_VARS = ["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5"];

const STATUS_KO: Record<string, string> = {
  proposed: "검토 대기",
  verified: "승인됨",
  rejected: "거부됨",
};

function statusKo(status: string): string {
  return STATUS_KO[String(status).toLowerCase()] ?? status ?? "—";
}

function statusVariant(status: string): "success" | "warning" | "error" | "secondary" {
  const key = String(status).toLowerCase();
  if (key === "verified") return "success";
  if (key === "proposed") return "warning";
  if (key === "rejected") return "error";
  return "secondary";
}

/** 차수가 큰 노드를 크게 — 크기로 구조를 읽게 한다. */
function nodeRadius(degree: number): number {
  return Math.min(16, 6 + 1.6 * Math.sqrt(degree));
}

/* ---------- 오류 문장 ----------
   api 클라이언트는 `"<status>: <body>"` 형태로 throw 한다. 사용자에게
   원문(raw)을 그대로 보여 주지 않고, 상태코드별 한국어 한 문장으로 번역한다. */

function errorText(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err ?? "");
  const status = Number(raw.match(/^(\d{3}):/)?.[1] ?? 0);
  if (status === 401) return "인증이 만료되었습니다. 화면을 새로고침해 다시 로그인합니다.";
  if (status === 403) return "이 자료를 볼 권한이 없습니다.";
  if (status === 404) return "대상을 찾을 수 없습니다. 이미 거부되었거나 보기 조건에서 제외되었습니다.";
  if (status === 422) return "요청 값이 올바르지 않습니다.";
  if (status === 429 || status === 503) return "서버가 혼잡합니다. 잠시 후 다시 시도합니다.";
  if (status >= 500) return "서버에서 오류가 발생했습니다.";
  if (!status) return "서버에 연결할 수 없습니다. 네트워크와 로컬 서버 상태를 확인합니다.";
  return "요청을 처리하지 못했습니다.";
}

/* ---------- 테마 색 ----------
   sigma는 WebGL이라 CSS 변수를 직접 못 읽는다. computed style의 사용값을
   1px 캔버스에 칠해 sRGB로 확정한다 — oklch()/color() 같은 함수 표기도 이
   경로면 실제 rgb가 나온다. */

interface ThemePalette {
  typeHex: string[];
  okRgb: string;
  warnRgb: string;
  pointRgb: string;
  fgHex: string;
  draftHex: string;
}

function probeColor(varName: string, fallback: string): { hex: string; rgb: string } {
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(varName)
    .trim();
  if (!raw) return { hex: fallback, rgb: "128,128,128" };
  const ctx = document.createElement("canvas").getContext("2d");
  if (!ctx) return { hex: fallback, rgb: "128,128,128" };
  ctx.fillStyle = raw;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  const hex = `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
  return { hex, rgb: `${r},${g},${b}` };
}

function readPalette(): ThemePalette {
  return {
    typeHex: TYPE_VARS.map((v) => probeColor(v, "#888888").hex),
    okRgb: probeColor("--ok", "134,180,120").rgb,
    warnRgb: probeColor("--warn", "200,160,80").rgb,
    pointRgb: probeColor("--point", "120,160,220").rgb,
    fgHex: probeColor("--foreground", "#cccccc").hex,
    draftHex: probeColor("--ink-draft", "#999999").hex,
  };
}

/** sigma는 WebGL2를 요구한다 — 지원 여부를 한 번만 검사한다. */
function supportsWebGL(): boolean {
  try {
    return Boolean(document.createElement("canvas").getContext("webgl2"));
  } catch {
    return false;
  }
}

/* ---------- 물리 한 스텝 ---------- */

function tick(
  nodes: SimNode[],
  edges: SimEdge[],
  index: Map<string, SimNode>,
  size: Size,
  alpha: number,
): void {
  /* 반발 — O(n²). limit 200 스코프에서는 이것으로 충분하고, 근사(quadtree)를
     넣으면 배치가 미묘하게 달라져 좌표 안정성을 다시 검증해야 한다. */
  for (let i = 0; i < nodes.length; i += 1) {
    for (let j = i + 1; j < nodes.length; j += 1) {
      const a = nodes[i];
      const b = nodes[j];
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      let d2 = dx * dx + dy * dy;
      if (d2 < 1) {
        /* 완전히 겹친 두 점은 힘의 방향이 없다 — 무작위로 떼어 놓는다. */
        dx = Math.random() - 0.5;
        dy = Math.random() - 0.5;
        d2 = 1;
      }
      if (d2 > REPULSION_CUTOFF) continue;
      const d = Math.sqrt(d2);
      const f = REPULSION / d2;
      a.vx -= (dx / d) * f;
      a.vy -= (dy / d) * f;
      b.vx += (dx / d) * f;
      b.vy += (dy / d) * f;
    }
  }

  /* 엣지 스프링 */
  for (const edge of edges) {
    const s = index.get(edge.source);
    const t = index.get(edge.target);
    if (!s || !t) continue;
    const ex = t.x - s.x;
    const ey = t.y - s.y;
    const ed = Math.hypot(ex, ey) || 1;
    const force = (ed - SPRING_LENGTH) * SPRING_K;
    s.vx += (ex / ed) * force;
    s.vy += (ey / ed) * force;
    t.vx -= (ex / ed) * force;
    t.vy -= (ey / ed) * force;
  }

  /* 중심 중력 + 적분 */
  for (const node of nodes) {
    node.vx += (size.w / 2 - node.x) * GRAVITY;
    node.vy += (size.h / 2 - node.y) * GRAVITY;
    if (node.fx != null && node.fy != null) {
      node.x = node.fx;
      node.y = node.fy;
      node.vx = 0;
      node.vy = 0;
      continue;
    }
    node.vx *= DAMPING;
    node.vy *= DAMPING;
    node.x += node.vx * alpha;
    node.y += node.vy * alpha;
  }
}

/* ========================================================================== */

export default function GraphPage() {
  const [includeProposed, setIncludeProposed] = React.useState(true);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [scene, setScene] = React.useState<{ nodes: SimNode[]; edges: SimEdge[] }>({
    nodes: [],
    edges: [],
  });
  const [legend, setLegend] = React.useState<{ type: string; color: string }[]>([]);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [expanding, setExpanding] = React.useState(false);
  const [expandError, setExpandError] = React.useState<string | null>(null);
  /* WebGL이 없으면 sigma를 올리지 않는다 — 캔버스만 안내문으로 대체하고
     목록·검색·상세는 그대로 살린다(앱 전체가 죽으면 안 된다). */
  const [webgl] = React.useState(supportsWebGL);
  const [canvasError, setCanvasError] = React.useState<string | null>(null);

  const [detail, setDetail] = React.useState<EntityDetail | null>(null);
  const [detailLoading, setDetailLoading] = React.useState(false);
  const [detailError, setDetailError] = React.useState<string | null>(null);

  const [query, setQuery] = React.useState("");
  const [hits, setHits] = React.useState<SearchHit[]>([]);
  const [searching, setSearching] = React.useState(false);
  const [searchError, setSearchError] = React.useState<string | null>(null);

  /* 시뮬레이션은 매 프레임 좌표를 바꾼다. 그것을 React 상태로 들고 있으면
     200개 노드가 60fps 로 리렌더된다 — 구조는 상태로, 좌표는 ref + 속성
     직접 쓰기로 나눈다. sigma는 graphRef의 graphology 인스턴스를 본다. */
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const graphRef = React.useRef<Graph>(new Graph());
  const sigmaRef = React.useRef<Sigma | null>(null);
  const nodesRef = React.useRef<SimNode[]>([]);
  const edgesRef = React.useRef<SimEdge[]>([]);
  const indexRef = React.useRef<Map<string, SimNode>>(new Map());
  const degreeRef = React.useRef<Map<string, number>>(new Map());
  const typeColorRef = React.useRef<Map<string, string>>(new Map());
  const paletteRef = React.useRef<ThemePalette>({
    typeHex: [],
    okRgb: "134,180,120",
    warnRgb: "200,160,80",
    pointRgb: "120,160,220",
    fgHex: "#cccccc",
    draftHex: "#999999",
  });
  const alphaRef = React.useRef(0);
  const rafRef = React.useRef<number | null>(null);
  const fitPendingRef = React.useRef(false);
  const selectedIdRef = React.useRef<string | null>(null);
  const detailSeqRef = React.useRef(0);
  const dragIdRef = React.useRef<string | null>(null);
  const queryRef = React.useRef("");

  selectedIdRef.current = selectedId;
  queryRef.current = query;

  const measure = React.useCallback((): Size => {
    const rect = containerRef.current?.getBoundingClientRect();
    return { w: rect?.width || 900, h: rect?.height || 520 };
  }, []);

  const typeColor = React.useCallback((type: string): string => {
    const known = typeColorRef.current.get(type);
    if (known) return known;
    const palette = paletteRef.current.typeHex;
    const next = palette[typeColorRef.current.size % Math.max(1, palette.length)] ?? "#888888";
    typeColorRef.current.set(type, next);
    return next;
  }, []);

  /* ---------- 좌표를 sigma에 반영 ---------- */

  const syncScene = React.useCallback(() => {
    const graph = graphRef.current;
    for (const node of nodesRef.current) {
      if (graph.hasNode(node.id)) {
        graph.setNodeAttribute(node.id, "x", node.x);
        graph.setNodeAttribute(node.id, "y", node.y);
      }
    }
    sigmaRef.current?.refresh();
  }, []);

  /* ---------- 화면 맞춤 ----------
     sigma의 framed 좌표계는 그래프 전체를 [0,1] 상자로 정규화하므로, 맞춤은
     카메라를 중심(0.5,0.5)으로 옮기고 표시된 노드 bbox가 채우는 비율만큼만
     잡으면 된다. 디스플레이 데이터가 아직 없으면 전체 보기로 되돌린다. */

  const fitToView = React.useCallback(() => {
    const sigma = sigmaRef.current;
    const graph = graphRef.current;
    if (!sigma || graph.order === 0) return;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    let complete = true;
    graph.forEachNode((id) => {
      const dd = sigma.getNodeDisplayData(id);
      if (!dd || !Number.isFinite(dd.x) || !Number.isFinite(dd.y)) {
        complete = false;
        return;
      }
      minX = Math.min(minX, dd.x);
      maxX = Math.max(maxX, dd.x);
      minY = Math.min(minY, dd.y);
      maxY = Math.max(maxY, dd.y);
    });
    const camera = sigma.getCamera();
    if (!complete || !Number.isFinite(minX) || !Number.isFinite(minY)) {
      camera.setState({ x: 0.5, y: 0.5, ratio: 1.05 });
      return;
    }
    /* framed 좌표는 정규화라 노드가 적을수록 bbox가 작게 나온다 — 작은
       그래프에서 과확대되지 않도록 필요 비율에 하한을 둔다. */
    const needed = Math.min(1.6, Math.max(0.4, Math.max(maxX - minX, maxY - minY) * 1.12));
    camera.animate(
      { x: (minX + maxX) / 2, y: (minY + maxY) / 2, ratio: needed },
      { duration: 250 },
    );
  }, []);

  /* ---------- rAF 루프 ---------- */

  const loop = React.useCallback(() => {
    /* 화면에서 빠지면(폭 0) 좌표가 엉뚱하게 드리프트하므로 루프를 멈춘다. */
    if (!containerRef.current || containerRef.current.getBoundingClientRect().width === 0) {
      rafRef.current = null;
      return;
    }
    if (alphaRef.current > ALPHA_MIN) {
      tick(nodesRef.current, edgesRef.current, indexRef.current, measure(), alphaRef.current);
      alphaRef.current *= ALPHA_DECAY;
      syncScene();
      rafRef.current = requestAnimationFrame(loop);
      return;
    }
    /* 가라앉은 뒤 한 번만 맞춘다. */
    if (fitPendingRef.current) {
      fitPendingRef.current = false;
      fitToView();
    }
    rafRef.current = null;
  }, [fitToView, measure, syncScene]);

  const reheat = React.useCallback(
    (alpha: number) => {
      alphaRef.current = Math.max(alphaRef.current, alpha);
      if (rafRef.current == null) rafRef.current = requestAnimationFrame(loop);
    },
    [loop],
  );

  /* ---------- 데이터 병합 ---------- */

  const mergePayload = React.useCallback(
    (payload: GraphPayload, anchor: SimNode | null) => {
      const size = measure();
      const cx = anchor ? anchor.x : size.w / 2;
      const cy = anchor ? anchor.y : size.h / 2;
      /* 확장이면 앵커 근처에 좁게 흩뿌려 "여기서 자라났다"가 보이게 한다. */
      const spread = anchor ? 90 : Math.max(size.w, size.h) * 0.7;
      const graph = graphRef.current;

      for (const raw of payload.nodes ?? []) {
        if (indexRef.current.has(raw.id)) continue;
        const node: SimNode = {
          id: raw.id,
          name: raw.name || raw.id.slice(0, 8),
          entityType: raw.entity_type || "?",
          status: raw.status ?? "proposed",
          confidence: raw.confidence ?? null,
          x: cx + (Math.random() - 0.5) * spread,
          y: cy + (Math.random() - 0.5) * spread,
          vx: 0,
          vy: 0,
          fx: null,
          fy: null,
        };
        indexRef.current.set(node.id, node);
        nodesRef.current.push(node);
        if (!graph.hasNode(node.id)) {
          graph.addNode(node.id, {
            x: node.x,
            y: node.y,
            label: node.name,
            entityType: node.entityType,
            status: node.status,
            size: nodeRadius(0),
            type: "status",
          });
        }
      }

      const seen = new Set(edgesRef.current.map((e) => e.id));
      for (const raw of payload.edges ?? []) {
        if (seen.has(raw.id)) continue;
        /* traverse 가 limit 로 끊기면 한쪽 끝이 없는 엣지가 올 수 있다. */
        if (!indexRef.current.has(raw.source_id) || !indexRef.current.has(raw.target_id)) continue;
        seen.add(raw.id);
        edgesRef.current.push({
          id: raw.id,
          source: raw.source_id,
          target: raw.target_id,
          relationType: raw.relation_type,
          status: raw.status,
        });
        if (!graph.hasEdge(raw.id)) {
          graph.addEdgeWithKey(raw.id, raw.source_id, raw.target_id, {
            status: raw.status,
            size: 1.4,
          });
        }
      }

      const degree = new Map<string, number>();
      for (const edge of edgesRef.current) {
        degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
        degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
      }
      degreeRef.current = degree;
      for (const node of nodesRef.current) {
        if (graph.hasNode(node.id)) {
          graph.setNodeAttribute(node.id, "size", nodeRadius(degree.get(node.id) ?? 0));
        }
      }

      for (const node of nodesRef.current) typeColor(node.entityType);
      setLegend(
        [...typeColorRef.current.entries()].map(([type, color]) => ({ type, color })),
      );
      setScene({ nodes: [...nodesRef.current], edges: [...edgesRef.current] });
      syncScene();
    },
    [measure, syncScene, typeColor],
  );

  /* ---------- 전체 그래프 적재 ---------- */

  const loadGraph = React.useCallback(
    async (proposed: boolean) => {
      setLoading(true);
      setError(null);
      setExpandError(null);
      try {
        const payload = await get<GraphPayload>(
          `/graph?limit=${NODE_LIMIT}&include_proposed=${proposed ? "true" : "false"}`,
        );
        /* 보기 조건이 바뀌면 배치를 처음부터 다시 잡는다. */
        nodesRef.current = [];
        edgesRef.current = [];
        indexRef.current = new Map();
        degreeRef.current = new Map();
        typeColorRef.current = new Map();
        graphRef.current.clear();
        detailSeqRef.current += 1;
        setSelectedId(null);
        setDetail(null);
        setDetailError(null);
        mergePayload(payload, null);
        fitPendingRef.current = true;
        reheat(1);
      } catch (err) {
        setError(errorText(err));
        setScene({ nodes: [], edges: [] });
        setLegend([]);
      } finally {
        setLoading(false);
      }
    },
    [mergePayload, reheat],
  );

  React.useEffect(() => {
    void loadGraph(includeProposed);
  }, [includeProposed, loadGraph]);

  React.useEffect(
    () => () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    },
    [],
  );

  /* 캔버스 크기가 바뀌면 중력의 중심이 옮겨진다 — 다시 데운다. */
  React.useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (nodesRef.current.length > 0) {
        fitPendingRef.current = true;
        reheat(0.25);
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [reheat]);

  /* ---------- sigma 장착 ----------
     한 번 만든다. 데이터는 graphRef의 graphology 인스턴스를 공유하므로
     병합/리셋은 그래프 쪽만 바꾸면 된다. */

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container || !webgl) return;
    paletteRef.current = readPalette();

    let sigma: Sigma;
    try {
      sigma = new Sigma(graphRef.current, container, {
      nodeProgramClasses: { status: NodeStatusProgram },
      defaultNodeType: "status",
      labelFont: getComputedStyle(document.body).fontFamily,
      labelSize: LABEL_BASE_PX,
      labelWeight: "500",
      labelColor: { attribute: "labelColor" },
      labelDensity: 0.08,
      labelGridCellSize: 110,
      labelRenderedSizeThreshold: 5,
      minCameraRatio: 0.25,
      maxCameraRatio: 4.5,
      stagePadding: 28,
      zIndex: true,
      /* 데이터 상태는 노드 속성에, 상호작용 상태(선택 후광·검색 흐림)는
         리듀서가 매 프레임 ref를 읽어 계산한다 — 그래프 속성을 만지지 않아
         200 노드 기준으로도 부담이 없다. */
      nodeReducer: (node, data) => {
        const needle = queryRef.current.trim().toLowerCase();
        const dimmed =
          Boolean(needle) && !String(data.label ?? "").toLowerCase().includes(needle);
        const selected = selectedIdRef.current === node;
        const palette = paletteRef.current;
        const status = String(data.status ?? "proposed");
        /* nodeReducer output replaces the node's display data — dropping x/y
           makes Sigma throw "could not find a valid position" and unmount the
           tree. Spread data so the position passes through. */
        const res: Partial<NodeDisplayData> & Record<string, unknown> = {
          ...data,
          color: typeColorRef.current.get(String(data.entityType ?? "?")) ?? "#888888",
          ringColor:
            status === "verified" ? `rgba(${palette.okRgb},0.9)` : `rgba(${palette.warnRgb},0.85)`,
          haloColor: selected ? `rgba(${palette.pointRgb},0.85)` : "#00000000",
          dashed: status !== "verified",
          dimmed,
          labelColor: status === "verified" ? palette.fgHex : palette.draftHex,
        };
        if (dimmed) res.label = "";
        return res;
      },
      edgeReducer: (_edge, data) => ({
        color:
          String(data.status ?? "proposed") === "verified"
            ? `rgba(${paletteRef.current.okRgb},0.75)`
            : `rgba(${paletteRef.current.warnRgb},0.32)`,
      }),
      });
    } catch (err) {
      /* WebGL 컨텍스트가 런타임에 거절되는 경우(GPU 블록리스트 등) —
         캔버스만 안내문으로 대체하고 페이지의 나머지는 살린다. */
      setCanvasError(err instanceof Error ? err.message : String(err));
      return;
    }

    /* 포인터 제스처는 전부 이름 있는 액션으로 흐른다. */
    sigma.on("clickNode", (event) => selectRef.current(event.node));
    sigma.on("clickStage", () => selectRef.current(null));
    sigma.on("doubleClickNode", (event) => expandRef.current(event.node));

    sigma.on("downNode", (event) => {
      dragIdRef.current = event.node;
      const node = indexRef.current.get(event.node);
      if (node) {
        node.fx = node.x;
        node.fy = node.y;
      }
      sigma.getCamera().disable();
    });
    sigma.on("enterNode", () => {
      container.style.cursor = "pointer";
    });
    sigma.on("leaveNode", () => {
      container.style.cursor = "";
    });

    const captor = sigma.getMouseCaptor();
    const onDragMove = (event: { x: number; y: number }) => {
      const id = dragIdRef.current;
      if (!id) return;
      const node = indexRef.current.get(id);
      if (!node) return;
      const point = sigma.viewportToGraph({ x: event.x, y: event.y });
      node.fx = point.x;
      node.fy = point.y;
      node.x = point.x;
      node.y = point.y;
      reheat(0.35);
    };
    const onDragEnd = () => {
      const id = dragIdRef.current;
      if (id) {
        const node = indexRef.current.get(id);
        if (node) {
          node.fx = null;
          node.fy = null;
        }
      }
      dragIdRef.current = null;
      sigma.getCamera().enable();
    };
    captor.on("mousemovebody", onDragMove);
    captor.on("mouseup", onDragEnd);

    sigmaRef.current = sigma;
    return () => {
      sigma.kill();
      sigmaRef.current = null;
    };
  }, [reheat, webgl]);

  /* 테마가 바뀌면 팔레트를 다시 읽고 다시 칠한다 — 색은 reducer가 매
     프레임 팔레트를 참조하므로 리프레시만으로 충분하다. */
  React.useEffect(() => {
    if (typeof MutationObserver === "undefined") return;
    const observer = new MutationObserver(() => {
      paletteRef.current = readPalette();
      sigmaRef.current?.refresh();
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => observer.disconnect();
  }, []);

  /* ---------- 상세 ---------- */

  const loadDetail = React.useCallback(async (id: string) => {
    const seq = ++detailSeqRef.current;
    setDetailLoading(true);
    setDetailError(null);
    try {
      /* 자유 탐색용 엔티티 상세는 review 컨텍스트가 그대로 담고 있다
         (엔티티 + 관계 + 출처 + 크리틱 점수). 별도 엔드포인트는 없다. */
      const payload = await get<EntityDetail>(`/entity/${encodeURIComponent(id)}/review`);
      if (seq !== detailSeqRef.current) return;
      /* HTTP 응답은 시스템 경계다 — 목록 필드가 빠진 응답 하나가 화면 전체를
         내리지 않도록 여기서 한 번만 정규화한다. JSX 안에 옵셔널 체이닝을
         흩뿌리는 대신 경계에서 형태를 보장한다. */
      setDetail({
        ...payload,
        entity: { ...payload.entity, aliases: payload.entity?.aliases ?? [] },
        relations: payload.relations ?? [],
        mentions: payload.mentions ?? [],
        counts: {
          mentions: payload.counts?.mentions ?? 0,
          relations_proposed: payload.counts?.relations_proposed ?? 0,
          relations_verified: payload.counts?.relations_verified ?? 0,
          merge_candidates: payload.counts?.merge_candidates ?? 0,
        },
      });
    } catch (err) {
      if (seq !== detailSeqRef.current) return;
      setDetail(null);
      setDetailError(errorText(err));
    } finally {
      if (seq === detailSeqRef.current) setDetailLoading(false);
    }
  }, []);

  /* ---------- 이름 있는 액션 ----------

     selectNode  — 노드 선택: 후광을 켜고 상세 패널을 연다.
     inspectNode — 상세 보기: 선택된 노드의 상세를 (다시) 불러온다.
     expandNeighbors — 이웃 펼치기: 한 홉 이웃을 씬에 합친다. */

  const inspectNode = React.useCallback(
    (id: string) => {
      void loadDetail(id);
    },
    [loadDetail],
  );

  const selectNode = React.useCallback(
    (id: string | null) => {
      setSelectedId(id);
      selectedIdRef.current = id;
      sigmaRef.current?.refresh();
      if (!id) {
        detailSeqRef.current += 1;
        setDetail(null);
        setDetailError(null);
        setDetailLoading(false);
        return;
      }
      inspectNode(id);
    },
    [inspectNode],
  );

  const expandNeighbors = React.useCallback(
    async (id: string) => {
      const anchor = indexRef.current.get(id);
      if (!anchor) return;
      setExpanding(true);
      setExpandError(null);
      try {
        const payload = await get<GraphPayload>(
          `/graph/neighbors/${encodeURIComponent(id)}?hops=1&include_proposed=${
            includeProposed ? "true" : "false"
          }`,
        );
        mergePayload(payload, anchor);
        reheat(0.6);
      } catch (err) {
        setExpandError(errorText(err));
      } finally {
        setExpanding(false);
      }
    },
    [includeProposed, mergePayload, reheat],
  );

  /* sigma의 once-effect 핸들러는 ref를 통해 항상 최신 액션을 부른다. */
  const selectRef = React.useRef(selectNode);
  const expandRef = React.useRef(expandNeighbors);
  selectRef.current = selectNode;
  expandRef.current = expandNeighbors;

  /* ---------- 검색 ----------
     서버 이름 검색. 마지막 입력만 반영하도록 세대 번호로 늦게 온 응답을 버린다. */

  const searchSeqRef = React.useRef(0);

  React.useEffect(() => {
    const needle = query.trim();
    if (needle.length === 0) {
      setHits([]);
      setSearching(false);
      setSearchError(null);
      sigmaRef.current?.refresh();
      return;
    }
    const seq = searchSeqRef.current + 1;
    searchSeqRef.current = seq;
    setSearching(true);
    const timer = window.setTimeout(async () => {
      try {
        const payload = await get<SearchPayload>(
          `/search?q=${encodeURIComponent(needle)}&limit=8`,
        );
        if (searchSeqRef.current !== seq) return;
        setHits(payload.results ?? []);
        setSearchError(null);
      } catch (err) {
        if (searchSeqRef.current !== seq) return;
        setHits([]);
        setSearchError(errorText(err));
      } finally {
        if (searchSeqRef.current === seq) setSearching(false);
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  /* 검색어가 바뀌면 강조(가라앉힘)를 즉시 반영한다. */
  React.useEffect(() => {
    sigmaRef.current?.refresh();
  }, [query, scene]);

  /** 검색 결과를 고르면: 화면에 있으면 선택, 없으면 이웃을 불러 합친다. */
  const openHit = React.useCallback(
    async (hit: SearchHit) => {
      if (indexRef.current.has(hit.id)) {
        selectNode(hit.id);
        const sigma = sigmaRef.current;
        const dd = sigma?.getNodeDisplayData(hit.id);
        if (sigma && dd) {
          /* 고른 것을 화면 가운데로 — 목록에서 골랐는데 어디 있는지 못 찾으면
             검색이 제 일을 못한 것이다. */
          fitPendingRef.current = false;
          sigma.getCamera().animate({ x: dd.x, y: dd.y }, { duration: 250 });
        }
        return;
      }
      setExpanding(true);
      setExpandError(null);
      try {
        const payload = await get<GraphPayload>(
          `/graph/neighbors/${encodeURIComponent(hit.id)}?hops=1&include_proposed=${
            includeProposed ? "true" : "false"
          }`,
        );
        mergePayload(payload, null);
        fitPendingRef.current = true;
        reheat(0.8);
        selectNode(hit.id);
      } catch (err) {
        setExpandError(errorText(err));
      } finally {
        setExpanding(false);
      }
    },
    [includeProposed, mergePayload, reheat, selectNode],
  );

  /* ---------- 키보드 ----------
     WebGL 노드는 DOM 포커스를 받지 못한다 — 캔버스가 포커스를 받고
     화살표키로 선택을 옮긴다(구 구현의 노드별 tabIndex를 대신한다). */
  const focusIdxRef = React.useRef(-1);

  const onCanvasKeyDown = (ev: React.KeyboardEvent<HTMLDivElement>) => {
    const nodes = nodesRef.current;
    if (nodes.length === 0) return;
    if (ev.key === "ArrowRight" || ev.key === "ArrowDown") {
      ev.preventDefault();
      focusIdxRef.current = Math.min(focusIdxRef.current + 1, nodes.length - 1);
      selectNode(nodes[focusIdxRef.current].id);
    } else if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") {
      ev.preventDefault();
      focusIdxRef.current = Math.max(focusIdxRef.current - 1, 0);
      selectNode(nodes[focusIdxRef.current].id);
    } else if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      if (selectedId) inspectNode(selectedId);
    } else if (ev.key === "e" || ev.key === "E") {
      ev.preventDefault();
      if (selectedId) void expandNeighbors(selectedId);
    } else if (ev.key === "Escape") {
      selectNode(null);
    }
  };

  const selectedNode = selectedId ? indexRef.current.get(selectedId) ?? null : null;
  const isEmpty = !loading && !error && scene.nodes.length === 0;

  return (
    <div className="flex min-h-full flex-col gap-4 p-6 lg:h-full">
      <style>{GRAPH_CSS}</style>

      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <Network className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
          그래프
        </h1>
        <p className="text-xs text-muted-foreground">
          노드를 누르면 상세가 열립니다 · 두 번 누르면 이웃을 펼칩니다 · 화살표키로 노드 이동 ·
          승인과 거부는 검토 화면에서 수행합니다
        </p>
      </header>

      {/* ---------- 도구 모음 ---------- */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-60 flex-1">
          <Search
            className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            value={query}
            onChange={(ev) => setQuery(ev.target.value)}
            type="search"
            placeholder="이름으로 개념 검색…"
            aria-label="개념 이름 검색"
            autoComplete="off"
            className="pl-9"
          />
          {searching ? (
            <Loader2
              className="absolute top-1/2 right-3 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground"
              aria-hidden="true"
            />
          ) : null}

          {/* 검색 결과 — 고르면 화면으로 데려간다 */}
          {query.trim() && (hits.length > 0 || searchError || (!searching && hits.length === 0)) ? (
            <div className="absolute top-full left-0 z-20 mt-1 w-full overflow-hidden rounded-md border bg-popover">
              {searchError ? (
                <p className="px-3 py-2 text-xs text-destructive">{searchError}</p>
              ) : hits.length === 0 ? (
                <p className="px-3 py-2 text-xs text-muted-foreground">
                  일치하는 개념이 없습니다.
                </p>
              ) : (
                <ScrollArea className="max-h-64">
                  <ul>
                    {hits.map((hit) => (
                      <li key={hit.id}>
                        <button
                          type="button"
                          onClick={() => void openHit(hit)}
                          className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
                        >
                          <span className="truncate">{hit.name}</span>
                          <span className="flex shrink-0 items-center gap-1.5">
                            <span className="text-xs text-muted-foreground">{hit.entity_type}</span>
                            <Badge variant={statusVariant(hit.status)}>{statusKo(hit.status)}</Badge>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </ScrollArea>
              )}
            </div>
          ) : null}
        </div>

        <Button
          type="button"
          variant={includeProposed ? "secondary" : "outline"}
          size="sm"
          onClick={() => setIncludeProposed((prev) => !prev)}
          aria-pressed={includeProposed}
        >
          {includeProposed ? (
            <Eye className="h-4 w-4" aria-hidden="true" />
          ) : (
            <EyeOff className="h-4 w-4" aria-hidden="true" />
          )}
          {includeProposed ? "제안 포함" : "승인된 것만"}
        </Button>

        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void loadGraph(includeProposed)}
          disabled={loading}
        >
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} aria-hidden="true" />
          새로고침
        </Button>

        <Button type="button" variant="outline" size="sm" onClick={fitToView} disabled={isEmpty}>
          <Crosshair className="h-4 w-4" aria-hidden="true" />
          화면에 맞춤
        </Button>

        <span className="text-xs text-muted-foreground tabular-nums">
          노드 {scene.nodes.length} · 관계 {scene.edges.length}
        </span>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>그래프를 불러오지 못했습니다</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            <span>{error}</span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void loadGraph(includeProposed)}
            >
              다시 시도
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      {expandError ? (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>이웃을 펼치지 못했습니다</AlertTitle>
          <AlertDescription>{expandError}</AlertDescription>
        </Alert>
      ) : null}

      {/* ---------- 캔버스 + 상세 ---------- */}
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="relative min-h-[420px] overflow-hidden rounded-lg border bg-card">
          {loading ? (
            <div className="absolute inset-0 z-10 grid place-items-center gap-3 p-6">
              <div className="flex w-full max-w-sm flex-col items-center gap-3">
                <Skeleton className="h-32 w-32 rounded-full" />
                <Skeleton className="h-3 w-40" />
                <Skeleton className="h-3 w-28" />
                <p className="text-xs text-muted-foreground">그래프를 불러옵니다…</p>
              </div>
            </div>
          ) : null}

          {isEmpty ? (
            <div className="absolute inset-0 z-10 grid place-items-center p-6">
              <div className="flex max-w-sm flex-col items-center gap-2 text-center">
                <Share2 className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
                <p className="text-md font-semibold">표시할 그래프가 없습니다</p>
                <p className="text-sm text-muted-foreground">
                  {includeProposed
                    ? "리서치를 실행하면 제안 노드가 만들어집니다."
                    : "승인된 개념이 아직 없습니다. 제안을 포함해 보거나 검토 화면에서 승인합니다."}
                </p>
                {!includeProposed ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setIncludeProposed(true)}
                  >
                    <Eye className="h-4 w-4" aria-hidden="true" />
                    제안 포함해 보기
                  </Button>
                ) : null}
              </div>
            </div>
          ) : null}

          <div
            ref={containerRef}
            className="g-canvas block h-full w-full outline-none"
            role="application"
            aria-label="지식그래프 탐색 화면. 화살표키로 노드를 이동하고 엔터로 상세를 엽니다."
            tabIndex={0}
            data-nodes={scene.nodes.length}
            data-edges={scene.edges.length}
            onKeyDown={onCanvasKeyDown}
          />

          {/* WebGL이 없거나 sigma가 거절되면 캔버스 자리에 한계를 명시한다 —
             목록·검색·상세·확장은 아래 숨겨진 목록을 통해 계속 동작한다. */}
          {(!webgl || canvasError) && !loading && !isEmpty ? (
            <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center p-6">
              <div className="max-w-sm space-y-1.5 rounded-md border bg-card/95 p-4 text-center shadow-sm">
                <p className="text-sm font-medium">
                  이 브라우저에서는 그래프 화면을 그릴 수 없습니다
                </p>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {webgl
                    ? `WebGL 캔버스 초기화가 거절되었습니다(${canvasError ?? "알 수 없는 오류"}).`
                    : "이 환경은 WebGL2를 지원하지 않습니다."}{" "}
                  노드 목록·검색·상세 보기는 그대로 사용할 수 있습니다.
                </p>
              </div>
            </div>
          ) : null}

          {/* WebGL 노드는 스크린리더가 못 읽는다 — 숨겨진 목록이 같은 지형을
             AT·키보드 탐색·테스트에 제공한다. 클릭과 엔터는 selectNode로 흐른다. */}
          <ul className="sr-only" aria-label="그래프 노드 목록">
            {scene.nodes.map((node) => (
              <li key={node.id}>
                <button
                  type="button"
                  className={cn("g-node", selectedId === node.id && "g-selected")}
                  data-id={node.id}
                  data-status={node.status}
                  aria-label={`${node.name} · ${node.entityType} · ${statusKo(node.status)}`}
                  onClick={() => selectNode(node.id)}
                >
                  {node.name}
                </button>
              </li>
            ))}
          </ul>

          {/* 범례 — 두 색 축을 모두 설명해야 화면을 읽을 수 있다 */}
          {!isEmpty && !loading ? (
            <div
              className="pointer-events-none absolute top-3 left-3 flex max-w-[60%] flex-wrap gap-1.5"
              aria-hidden="true"
            >
              {legend.map((item) => (
                <span key={item.type} className="g-chip">
                  <i style={{ background: item.color }} />
                  {item.type}
                </span>
              ))}
              <span className="g-chip">
                <i className="g-chip-proposed" />
                점선 = 검토 대기
              </span>
              <span className="g-chip">
                <i className="g-chip-verified" />
                실선 = 승인됨
              </span>
            </div>
          ) : null}

          {/* 선택한 노드 요약 — 세 액션(상세 보기 · 이웃 펼치기 · 선택 해제)을
             이름 붙은 버튼으로도 제공한다 */}
          {selectedNode ? (
            <Card className="absolute top-3 right-3 w-64">
              <CardHeader className="flex-row items-start justify-between gap-2 space-y-0 p-4">
                <div className="min-w-0">
                  <CardTitle className="truncate text-md">{selectedNode.name}</CardTitle>
                  <CardDescription className="mt-1 text-xs">
                    {selectedNode.entityType} · 연결{" "}
                    {degreeRef.current.get(selectedNode.id) ?? 0}개
                    {selectedNode.confidence == null
                      ? ""
                      : ` · 확신도 ${selectedNode.confidence.toFixed(2)}`}
                  </CardDescription>
                </div>
                <button
                  type="button"
                  onClick={() => selectNode(null)}
                  aria-label="선택 해제"
                  className="shrink-0 rounded-sm text-muted-foreground transition-colors hover:text-foreground"
                >
                  <X className="h-4 w-4" aria-hidden="true" />
                </button>
              </CardHeader>
              <CardContent className="flex flex-wrap items-center gap-2 p-4 pt-0">
                <Badge variant={statusVariant(selectedNode.status)}>
                  {statusKo(selectedNode.status)}
                </Badge>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => inspectNode(selectedNode.id)}
                  disabled={detailLoading}
                >
                  {detailLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <MousePointer2 className="h-4 w-4" aria-hidden="true" />
                  )}
                  상세 보기
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void expandNeighbors(selectedNode.id)}
                  disabled={expanding}
                >
                  {expanding ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <Share2 className="h-4 w-4" aria-hidden="true" />
                  )}
                  이웃 펼치기
                  {detail && detail.relations.length > 0
                    ? ` (${detail.relations.length})`
                    : ""}
                </Button>
                {detail &&
                nodesRef.current.length + detail.relations.length > NODE_LIMIT ? (
                  <p className="w-full text-xs text-warn-text">
                    현재 {nodesRef.current.length}개 + 이웃{" "}
                    {detail.relations.length}개 = 표시 한도 {NODE_LIMIT}개를 넘을 수
                    있습니다. 일부만 표시됩니다.
                  </p>
                ) : null}
              </CardContent>
            </Card>
          ) : null}
        </div>

        {/* ---------- 상세 패널 ---------- */}
        <Card className="g-detail flex min-h-0 flex-col overflow-hidden">
          <CardHeader className="p-4">
            <CardTitle className="text-md">개념 상세</CardTitle>
            <CardDescription className="text-xs">
              {selectedId ? "선택한 개념의 출처와 관계입니다." : "노드를 선택하면 표시됩니다."}
            </CardDescription>
          </CardHeader>
          <CardContent className="min-h-0 flex-1 p-0">
            {!selectedId ? (
              <p className="px-4 pb-4 text-sm text-muted-foreground">
                캔버스에서 노드를 누르거나, 위 검색에서 개념을 고릅니다.
              </p>
            ) : detailLoading ? (
              <div className="flex flex-col gap-2 px-4 pb-4">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-5/6" />
                <Skeleton className="h-3 w-2/3" />
              </div>
            ) : detailError ? (
              <div className="px-4 pb-4">
                <Alert variant="destructive">
                  <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                  <AlertTitle>상세를 불러오지 못했습니다</AlertTitle>
                  <AlertDescription className="flex flex-wrap items-center gap-2">
                    <span>{detailError}</span>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => void loadDetail(selectedId)}
                    >
                      다시 시도
                    </Button>
                  </AlertDescription>
                </Alert>
              </div>
            ) : detail ? (
              <ScrollArea className="h-full">
                <div className="flex flex-col gap-4 px-4 pb-4">
                  <div className="flex flex-col gap-1.5">
                    <p className="text-md font-semibold">{detail.entity.name}</p>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge variant="outline">{detail.entity.entity_type}</Badge>
                      <Badge variant={statusVariant(detail.entity.status)}>
                        {statusKo(detail.entity.status)}
                      </Badge>
                      {detail.entity.confidence == null ? null : (
                        <span className="text-xs text-muted-foreground tabular-nums">
                          확신도 {detail.entity.confidence.toFixed(2)}
                        </span>
                      )}
                    </div>
                    <p className="font-mono text-xs text-muted-foreground" title={detail.entity.id}>
                      {detail.entity.id.slice(0, 18)}
                      {detail.entity.id.length > 18 ? "…" : ""}
                    </p>
                  </div>

                  {detail.entity.aliases.length > 0 ? (
                    <section className="flex flex-col gap-1.5">
                      <h2 className="text-label font-semibold tracking-label text-muted-foreground uppercase">
                        다른 이름
                      </h2>
                      <div className="flex flex-wrap gap-1.5">
                        {detail.entity.aliases.map((alias) => (
                          <Badge key={alias} variant="secondary">
                            {alias}
                          </Badge>
                        ))}
                      </div>
                    </section>
                  ) : null}

                  {detail.critic ? (
                    <section className="flex flex-col gap-1.5">
                      <h2 className="text-label font-semibold tracking-label text-muted-foreground uppercase">
                        크리틱 점수 (참고용)
                      </h2>
                      <p className="text-sm tabular-nums">
                        {detail.critic.score.toFixed(2)}
                        <span className="ml-1.5 text-xs text-muted-foreground">
                          {detail.critic.engine}
                        </span>
                      </p>
                      {detail.critic.rationale ? (
                        <p className="text-xs text-muted-foreground">{detail.critic.rationale}</p>
                      ) : null}
                    </section>
                  ) : null}

                  <section className="flex flex-col gap-1.5">
                    <h2 className="text-label font-semibold tracking-label text-muted-foreground uppercase">
                      관계 {detail.relations.length}개 · 승인 {detail.counts.relations_verified} · 대기{" "}
                      {detail.counts.relations_proposed}
                    </h2>
                    {detail.relations.length === 0 ? (
                      <p className="text-sm text-muted-foreground">아직 연결된 관계가 없습니다.</p>
                    ) : (
                      <ul className="flex flex-col gap-1">
                        {detail.relations.map((relation) => (
                          <li key={relation.id}>
                            <button
                              type="button"
                              onClick={() => void openHit({
                                id: relation.other.id,
                                name: relation.other.name,
                                entity_type: "",
                                status: relation.other.status,
                                score: null,
                              })}
                              className="flex w-full flex-col items-start gap-0.5 rounded-sm px-2 py-1.5 text-left transition-colors hover:bg-accent"
                            >
                              <span className="flex w-full items-center gap-1.5">
                                <span className="text-xs text-muted-foreground">
                                  {relation.direction === "out" ? "→" : "←"}
                                </span>
                                <span className="min-w-0 flex-1 truncate text-sm">
                                  {relation.other.name}
                                </span>
                                <span
                                  className={cn(
                                    "h-1.5 w-1.5 shrink-0 rounded-full",
                                    relation.status === "verified" ? "bg-ok" : "bg-warn",
                                  )}
                                  aria-hidden="true"
                                />
                              </span>
                              <span className="pl-5 text-xs text-muted-foreground">
                                {relation.relation_type} · {statusKo(relation.status)}
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>

                  <section className="flex flex-col gap-1.5">
                    <h2 className="text-label font-semibold tracking-label text-muted-foreground uppercase">
                      출처 {detail.counts.mentions}곳
                    </h2>
                    {detail.mentions.length === 0 ? (
                      <p className="text-sm text-muted-foreground">연결된 출처가 없습니다.</p>
                    ) : (
                      <ul className="flex flex-col gap-2">
                        {detail.mentions.slice(0, 5).map((mention, i) => (
                          <li
                            key={`${mention.source_doc_id}-${i}`}
                            className="border-l-2 pl-2 text-xs"
                          >
                            <p className="font-medium">{mention.doc_title ?? "제목 없음"}</p>
                            <p className="mt-0.5 text-muted-foreground">{mention.excerpt}</p>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                </div>
              </ScrollArea>
            ) : null}
          </CardContent>
        </Card>
      </div>

      {/* ---------- 하단 상태 바 ---------- */}
      {!isEmpty && !loading ? (
        <footer className="flex items-center justify-between rounded-md border bg-card px-3 py-1.5 text-xs text-muted-foreground">
          <span>
            표시 {scene.nodes.length}개 노드 · {scene.edges.length}개 관계
            {scene.nodes.length >= NODE_LIMIT
              ? ` (한도 ${NODE_LIMIT}개)`
              : ""}
          </span>
          <span>
            {selectedNode
              ? `선택: ${selectedNode.name} · 연결 ${degreeRef.current.get(selectedNode.id) ?? 0}개`
              : "노드를 선택하면 상세가 표시됩니다"}
          </span>
        </footer>
      ) : null}
    </div>
  );
}

/* --------------------------------------------------------------------------
   캔버스와 범례 전용 규칙. Tailwind 유틸리티로는 표현할 수 없는 것만 남긴다.
   색은 전부 토큰을 참조한다 — 이 블록에 리터럴 색을 적지 말 것.
   -------------------------------------------------------------------------- */
const GRAPH_CSS = `
.g-canvas { cursor: grab; touch-action: none; user-select: none; }
.g-canvas:active { cursor: grabbing; }
.g-canvas:focus-visible { outline: 2px solid var(--ring); outline-offset: -2px; }

.g-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1, 4px);
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--card);
  font-size: var(--fs-xs);
  color: var(--muted-foreground);
}
.g-chip i { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.g-chip i.g-chip-proposed { background: transparent; border: 1.5px dashed var(--warn); }
.g-chip i.g-chip-verified { background: transparent; border: 1.5px solid var(--ok); }
`;
