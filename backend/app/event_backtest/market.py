from __future__ import annotations

from .models import EventRecord


# QQQ 前 20 大成分股（按权重，2025 口径）——遇到这些直接绑 QQQ
QQQ_COMPONENT_SYMBOLS = {
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "AVGO",
    "TSLA", "NFLX", "AMD", "COST", "PEP", "QCOM", "ADBE", "INTU",
    "AMAT", "CMCSA", "ORCL", "TXN",
}

# XLK 成分股典型代表（technology sector 纯科技硬件/半导体/软件）
XLK_COMPONENT_SYMBOLS = {
    "AAPL", "MSFT", "NVDA", "AVGO", "ADBE", "AMAT", "QCOM", "TXN",
    "AMD", "INTC", "ORCL", "CRM", "NOW", "SNPS", "CDNS", "ANSS",
    "KLAC", "LRCX", "MRVL", "MU",
}

US_TECH_KEYWORDS = {
    # 原有关键词
    "ai", "semiconductor", "chip", "chips", "cloud", "software", "saas",
    "internet", "platform",
    # 扩展：更宽泛的科技/互联网关键词，覆盖新闻标题常见词
    "technology", "tech", "gpu", "cpu", "asic", "fpga", "datacenter",
    "data center", "artificial intelligence", "machine learning",
    "large language model", "llm", "generative",
    "streaming", "social media", "e-commerce", "ecommerce",
    "semiconductor manufacturing", "wafer", "fabless", "foundry",
}


def resolve_benchmark(event: EventRecord) -> str:
    if event.benchmark:
        return event.benchmark
    if event.market == "CN":
        return "sh000300"
    if event.market == "HK":
        return "HSI"

    symbol = (event.symbol or "").strip().upper()
    # I2. 方案B1：symbol 级优先匹配 QQQ/XLK 成分股
    if symbol in XLK_COMPONENT_SYMBOLS:
        return "XLK"
    if symbol in QQQ_COMPONENT_SYMBOLS:
        return "QQQ"

    text = f"{event.event_type_l2} {event.title} {event.event_text}".lower()
    if any(k in text for k in US_TECH_KEYWORDS):
        return "QQQ"
    return "SPY"

