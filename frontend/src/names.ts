import type { AgentMeta } from "./types";

/** 技能名 → 中文名（design.md §4 技能清单） */
export const SKILL_CN: Record<string, string> = {
  search_stock: "股票搜索",
  get_stock_daily: "A股日K线",
  get_us_stock_daily: "美股日K线",
  get_index_daily: "指数日K",
  get_sector_spot: "行业板块快照",
  get_stock_news: "个股新闻",
  get_global_news: "财经快讯",
  get_announcements: "公告检索",
  get_financial_abstract: "财务摘要",
  get_financial_indicator: "财务指标",
  get_research_reports: "研报评级",
  get_lhb: "龙虎榜",
  get_margin: "融资融券",
  get_macro: "宏观指标",
  event_study: "事件研究",
  get_current_date: "当前日期",
  // 财务三表细表 + 业绩预告
  get_income_statement: "利润表",
  get_balance_sheet: "资产负债表",
  get_cash_flow: "现金流量表",
  get_profit_forecast: "业绩预告",
  // 板块
  list_industry_boards: "行业板块列表",
  get_industry_board_history: "行业板块K线",
  get_sector_fund_flow_rank: "板块资金流排名",
  get_board_change: "板块异动",
  get_stock_industry_info: "行业板块概况",
  // 资金流
  get_industry_fund_flow: "行业资金流",
  get_concept_fund_flow: "概念资金流",
  get_individual_fund_flow_rank: "个股资金流排名",
  get_big_deal_flow: "大单交易",
  get_hsgt_fund_flow: "北向资金",
  // 股东/解禁
  get_main_holders: "主要股东",
  get_circulate_holders: "流通股东",
  get_fund_holders: "基金持股",
  get_holder_change: "股东增减持",
  get_restricted_release_summary: "解禁汇总",
  get_restricted_release_detail: "解禁明细",
  // 跨市场
  get_etf_spot: "ETF实时",
  get_fund_value_estimation: "基金估值",
  get_futures_main: "期货主力",
  get_fx_spot_quote: "外汇牌价",
  get_convert_bond_spot: "可转债实时",
  get_us_index_daily: "美股指数K线",
  get_index_list: "全球指数列表",
  // 证据图（skill：1 个对外 + 9 个 _eg_* sub-tool，sub-tool 不暴露给前端）
  evidence_graph: "证据图操作",
  // skill —— LLM 可见的高层能力（agent 直接看到 skill，不看 atomic）
  stock_overview: "股票概览",
  market_research: "行情综合研究",
  financial_research: "财务综合研究",
  news_intel: "资讯情报",
  holder_research: "股东综合研究",
  macro_intel: "宏观情报",
  event_study_skill: "事件研究（CAR）",
  // _eg_* sub-tool（internal，LLM 不可见；仅留中文名以备将来展示 trace）
  _eg_add_evidence: "添加证据",
  _eg_add_claim: "添加推论",
  _eg_link: "链接证据↔推论",
  _eg_set_claim_status: "更新推论状态",
  _eg_merge_claims: "合并推论",
  _eg_add_missing: "记录研究缺口",
  _eg_set_sufficient: "标记研究充分",
  _eg_export: "导出证据图",
  _eg_clear: "重置证据图",
};

export function skillCn(name: string): string {
  return SKILL_CN[name] ?? name;
}

/** 未拿到花名册时的兜底配色（暖纸色系） */
const FALLBACK_AGENT_COLORS = ["#0F766E", "#B45309", "#7C5C3E", "#5B6B59", "#8A4B3A", "#4A5D6B"];

export function agentColor(agentId: string | undefined, agents: AgentMeta[]): string {
  if (!agentId) return "#6B6862";
  const found = agents.find((a) => a.id === agentId);
  if (found?.avatar_color) return found.avatar_color;
  let h = 0;
  for (const ch of agentId) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return FALLBACK_AGENT_COLORS[h % FALLBACK_AGENT_COLORS.length];
}

export function agentName(agentId: string | undefined, agents: AgentMeta[]): string {
  if (!agentId) return "Pronoia";
  return agents.find((a) => a.id === agentId)?.name ?? agentId;
}

export const KIND_CN: Record<string, string> = {
  kline: "K线图",
  line: "曲线图",
  table: "数据表",
  evidence: "证据",
  report: "研究报告",
  graph: "证据图",
};
