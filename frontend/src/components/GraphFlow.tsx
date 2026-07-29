import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { GraphChart } from "echarts/charts";
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  GraphChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  CanvasRenderer,
]);

const EDGE = "#E8E5E0";
const MUTE = "#6B6862";
const CARD = "#FFFFFF";
const FAINT = "#9C988F";

/** echarts 分类色（按 kind + claim status） */
const NODE_COLOR: Record<string, string> = {
  // evidence
  evidence: "#0F766E",          // 青
  // claim by status
  verified: "#2E9E5B",          // 绿
  rejected: "#D14343",          // 红
  needs_more: "#D08B1A",        // 橙
  insufficient: "#C25450",      // 暗红
  exploring: "#3D6B9E",         // 蓝
  // missing
  missing: "#B45309",           // 琥珀
};

const EDGE_COLOR: Record<string, string> = {
  supports: "#2E9E5B",
  contradicts: "#D14343",
  context: "#9C988F",
  addresses: "#3D6B9E",
};

const EDGE_LABEL: Record<string, string> = {
  supports: "支持",
  contradicts: "反驳",
  context: "上下文",
  addresses: "对应",
};

/** 节点：按 kind 分类（category 字段），并按 status 着色（itemStyle.color） */
function buildOption(payload: any) {
  const nodes: any[] = (payload?.nodes || []).map((n: any) => {
    const kind = n.kind || "evidence";
    // claim 用 status 当主色，其它按 kind
    const colorKey = kind === "claim" ? (n.status || "exploring") : kind;
    return {
      id: n.id,
      name: n.id,
      // category 用于图例分组
      category: kind,
      // itemStyle.color 控制节点填充
      itemStyle: { color: NODE_COLOR[colorKey] || NODE_COLOR[kind] || "#6B6862" },
      // symbolSize：claim 按 confidence 缩放，evidence/missing 固定
      symbolSize: kind === "claim" ? 28 + (n.confidence || 0.5) * 18 : 30,
      // label：默认显示 ID
      label: {
        show: true,
        position: "inside",
        color: "#FFFFFF",
        fontSize: 10,
        fontWeight: 600,
        formatter: "{b}",
      },
      // tooltip 自定义
      _title: n.title,
      _body: n.body,
      _kind: kind,
      _status: n.status,
      _confidence: n.confidence,
      _sourceRef: n.source_ref,
    };
  });

  const links: any[] = (payload?.edges || []).map((e: any) => ({
    source: e.src,
    target: e.dst,
    // link 个性化颜色通过 lineStyle.color 实现（series.lineStyle 默认值兜底）
    lineStyle: {
      color: EDGE_COLOR[e.relation] || MUTE,
      width: 1.4,
      opacity: 0.85,
    },
    // 给 edgeLabel.formatter 用的元数据（series.edgeLabel.show=true 才会显示）
    _relation: e.relation,
  }));

  // 补全缺失节点（如果某个 edge 的 src/dst 不在 nodes 里，echarts 会静默丢弃，
  // 这里给它们造一个隐形占位节点以保持图完整）
  const known = new Set(nodes.map((n) => n.id));
  for (const e of payload?.edges || []) {
    for (const x of [e.src, e.dst]) {
      if (!known.has(x)) {
        nodes.push({ id: x, name: x, category: "missing", itemStyle: { color: "#C9C4B9" }, symbolSize: 18, _title: "(未知节点)", _body: "", _kind: "missing" });
        known.add(x);
      }
    }
  }

  return {
    animationDurationUpdate: 600,
    animationEasingUpdate: "cubicOut",
    color: [NODE_COLOR.evidence, NODE_COLOR.exploring, NODE_COLOR.missing],
    textStyle: { fontFamily: "inherit" },
    tooltip: {
      trigger: "item",
      backgroundColor: CARD,
      borderColor: EDGE,
      textStyle: { color: "#1C1B1A", fontSize: 12 },
      extraCssText: "box-shadow: 0 2px 12px rgba(0,0,0,0.08); border-radius: 8px; max-width: 320px;",
      formatter: (params: any) => {
        if (params.dataType === "edge") {
          const rel = params.data?._relation || "关系";
          const color = EDGE_COLOR[rel] || MUTE;
          return `<div style="font-weight:600;color:${color}">${EDGE_LABEL[rel] || rel}</div>`;
        }
        const d = params.data || {};
        const status = d._status ? ` · <span style="color:${NODE_COLOR[d._status] || MUTE}">${d._status}</span>` : "";
        const conf = d._confidence != null ? ` · 置信度 ${Number(d._confidence).toFixed(2)}` : "";

        // 标题：限制每行 18 个汉字 / 36 字母，多行换行；最多 4 行
        const rawTitle = String(d._title || d.id);
        const wrappedTitle = wrapText(rawTitle, 18, 4);
        // body：限制每行 30 字符，限制总长，最多 6 行
        const rawBody = d._body ? String(d._body) : "";
        const wrappedBody = rawBody ? wrapText(rawBody, 30, 6) : "";

        const titleHtml = `<div style="font-weight:600;color:#1C1B1A;line-height:1.45;word-break:break-word;white-space:pre-wrap">${escapeHtml(wrappedTitle)}</div>`;
        const metaHtml = `<div style="margin-top:3px;font-size:11px;color:${MUTE};white-space:nowrap">${d.id}${status}${conf}</div>`;
        const bodyHtml = wrappedBody ? `<div style="margin-top:4px;color:${MUTE};max-width:280px;line-height:1.5;word-break:break-word;white-space:pre-wrap;overflow:hidden;display:-webkit-box;-webkit-line-clamp:6;-webkit-box-orient:vertical">${escapeHtml(wrappedBody)}</div>` : "";
        const src = d._sourceRef
          ? `<div style="margin-top:4px;font-family:monospace;font-size:10.5px;color:${FAINT};word-break:break-all;line-height:1.4">src: ${escapeHtml(String(d._sourceRef))}</div>`
          : "";
        return `${titleHtml}${metaHtml}${bodyHtml}${src}`;
      },
    },
    legend: {
      data: [
        { name: "evidence", label: "证据", itemStyle: { color: NODE_COLOR.evidence } },
        { name: "claim", label: "推论", itemStyle: { color: NODE_COLOR.exploring } },
        { name: "missing", label: "缺口", itemStyle: { color: NODE_COLOR.missing } },
      ],
      top: 4,
      left: "center",
      textStyle: { color: MUTE, fontSize: 11 },
      itemWidth: 10,
      itemHeight: 10,
    },
    series: [
      {
        type: "graph",
        layout: "force",
        roam: true,
        draggable: true,
        focusNodeAdjacency: true,
        categories: [
          { name: "evidence", itemStyle: { color: NODE_COLOR.evidence } },
          { name: "claim", itemStyle: { color: NODE_COLOR.exploring } },
          { name: "missing", itemStyle: { color: NODE_COLOR.missing } },
        ],
        data: nodes,
        links,
        force: {
          repulsion: 320,
          edgeLength: [60, 110],
          gravity: 0.08,
          friction: 0.18,
        },
        emphasis: {
          focus: "adjacency",
          lineStyle: { width: 2.5 },
          itemStyle: { borderColor: "#1C1B1A", borderWidth: 2 },
          label: { fontSize: 11, fontWeight: 700 },
        },
        // series 顶层的 lineStyle 才生效，links[].lineStyle.curveness 会被忽略
        // 也不要在 link 子项里设 label（会被 series.edgeLabel 覆盖但偶尔丢 link）
        lineStyle: { opacity: 0.85, curveness: 0.18, color: MUTE, width: 1.4 },
        edgeSymbol: ["none", "arrow"],
        edgeSymbolSize: 6,
        // 关系 label 走 series.edgeLabel，每条 link 通过 _relation 字段定制文案
        edgeLabel: {
          show: true,
          formatter: (params: any) => {
            const rel = params?.data?._relation || "关系";
            return EDGE_LABEL[rel] || rel;
          },
          fontSize: 9,
          color: MUTE,
          backgroundColor: "rgba(255,255,255,0.85)",
          padding: [1, 3],
          borderRadius: 3,
        },
        labelLayout: { hideOverlap: true },
        cursor: "pointer",
      },
    ],
  };
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/** 简单换行：按"近自然宽点"切，长度阈值 charsPerLine，最多 maxLines 行。
 * 优先在空格/标点处换行（避免英文词中间断），否则硬切。
 * 含中文（CJK）时按字符数算，含空白时按词算。
 */
function wrapText(text: string, charsPerLine: number, maxLines: number): string {
  if (!text) return "";
  // 预先把换行符去掉，再统一处理
  const flat = text.replace(/[\r\n]+/g, " ").trim();
  if (!flat) return "";

  // 判断是否包含 CJK 字符
  const hasCJK = /[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/.test(flat);

  // 切分策略：
  // - CJK 主导：按字符切，标点也单算 token（避免标点顶到行首）
  //   但同一组连续 ASCII 字符（数字串、英文短词）作为一个 token
  // - 西文：按空格切词；纯西文无空格（如 URL）时按字符切
  const tokens: string[] = [];
  if (hasCJK) {
    // 把连续 ASCII 看成一个 token（如 600519、Q3、Apple），
    // 其余 CJK 字符单算
    const re = /([A-Za-z0-9_:/.\-?&=+%@#]+)|([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(flat)) !== null) {
      tokens.push(m[0]);
    }
  } else if (/\s/.test(flat)) {
    tokens.push(...flat.split(/\s+/).filter(Boolean));
  } else {
    tokens.push(...Array.from(flat));
  }

  // 段内连接规则：
  // - 纯西文（token 之间会按空格显示）→ 用空格连接
  // - CJK → 紧贴（不加空格）
  const joinSep = hasCJK ? "" : " ";

  const lines: string[] = [];
  let current = "";
  let currentLen = 0;
  for (const t of tokens) {
    const tLen = displayWidth(t);
    if (currentLen === 0) {
      current = t;
      currentLen = tLen;
      continue;
    }
    const sepLen = displayWidth(joinSep);
    if (currentLen + sepLen + tLen <= charsPerLine) {
      current += joinSep + t;
      currentLen += sepLen + tLen;
    } else {
      lines.push(current);
      if (lines.length >= maxLines) break;
      current = t;
      currentLen = tLen;
    }
  }
  if (current && lines.length < maxLines) lines.push(current);

  // 如果超 maxLines，把最后一行用省略号收尾
  if (lines.length >= maxLines) {
    const usedChars = lines.reduce((s, l) => s + displayWidth(l), 0);
    if (usedChars < displayWidth(flat)) {
      const last = lines[lines.length - 1].replace(/[\s\u2026]+$/, "");
      lines[lines.length - 1] = last + "…";
    }
  }
  return lines.join("\n");
}

/** 估算 token 显示宽度：CJK 字符按 2，ASCII 按 1。 */
function displayWidth(s: string): number {
  let w = 0;
  for (const ch of s) {
    if (/[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/.test(ch)) w += 2;
    else w += 1;
  }
  return w;
}

/** 证据图力导向可视化：节点=evidence/claim/missing，边=supports/contradicts/context/addresses */
export default function GraphFlow({ payload, height = 420 }: { payload: any; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption(buildOption(payload) as any);

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.dispose();
    };
  }, [payload]);

  return <div ref={ref} style={{ height }} className="w-full" />;
}
