"""What counts as relevant: the screening rules, built for recall.

Four layers decide whether an item reaches the briefing (see feed.py):
  1. keyword  - the topic rules below, matched on full plain text
  2. department - every question to a watched department (e.g. DSIT)
  3. watchlist  - every question from a member who consistently drives these issues
  4. semantic   - an AI classifier reads everything layers 1-3 missed (semantic.py)
Precision is the writer and validator agents' job; this file errs on the side
of including too much. Add terms freely: whole words and phrases, case
insensitive, matched after HTML is stripped. Ambiguous words ('sovereign',
'frontier', 'outage', 'cloud') are tied to a technology context.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    patterns: tuple[str, ...]


def cs(*terms: str) -> tuple[str, ...]:
    """Case-sensitive whole-word patterns, for names that are also ordinary words (Apple, Meta, STEM)."""
    return tuple("(?-i:" + p + ")" for p in w(*terms))


def w(*terms: str) -> tuple[str, ...]:
    """Whole-word, whitespace- and hyphen-tolerant patterns for literal terms."""
    out = []
    for t in terms:
        parts = [re.escape(x) for x in re.split(r"[\s\-]+", t.strip()) if x]
        p = r"[\s\-]*".join(parts)          # "data centre" = "data-centre" = "datacentre"
        out.append(r"(?<![\w-])" + p + r"(?![\w])")
    return tuple(out)


TOPICS: tuple[Topic, ...] = (
    Topic("microsoft", "Microsoft and its businesses", w(
        "Microsoft", "Xbox", "LinkedIn", "GitHub", "Azure", "Copilot", "Activision", "Activision Blizzard",
        "Blizzard Entertainment", "Minecraft", "Bethesda", "Nuance", "Skype", "Microsoft Teams", "MS Teams",
        "Windows 10", "Windows 11", "Windows Server", "Office 365", "Microsoft 365", "M365", "Microsoft Outlook", "Bing",
        "Dynamics 365", "SharePoint", "OneDrive", "Power BI", "Azure OpenAI", "Microsoft Entra", "Intune", "Microsoft Defender",
        "Satya Nadella", "Brad Smith")),
    Topic("tech_companies", "Other technology and AI companies", w(
        "Google", "Alphabet", "DeepMind", "Google DeepMind", "YouTube", "Google Gemini", "Android", "Google Chrome",
        "Amazon", "Amazon Web Services", "AWS", "Alexa", "OpenAI", "ChatGPT", "GPT-4", "GPT-5", "Sora",
        "Anthropic", "Claude AI", "Nvidia", "Facebook", "Instagram", "WhatsApp", "iCloud",
        "Oracle", "IBM", "Salesforce", "Palantir", "Mistral", "xAI", "Grok", "DeepSeek", "Alibaba", "Huawei",
        "TikTok", "ByteDance", "Snapchat", "Twitter", "X Corp", "Elon Musk", "Arm Holdings", "TSMC",
        "Cisco", "Fujitsu", "Capita", "Atos", "Accenture", "Sopra Steria", "Kainos",
        "CrowdStrike", "Stargate", "Nscale", "CoreWeave", "Graphcore", "Wayve", "Synthesia", "Darktrace",
        "big tech", "tech giants", "tech companies", "technology companies", "hyperscaler", "hyperscalers")
        + cs("Apple", "Meta", "Intel", "AMD", "CGI", "Deloitte")),
    Topic("ai", "Artificial intelligence", w(
        "artificial intelligence", "AI", "A.I.", "AIs", "GenAI", "generative AI", "machine learning",
        "deep learning", "neural network", "neural networks", "large language model", "large language models",
        "LLM", "LLMs", "foundation model", "foundation models", "frontier AI", "frontier model",
        "frontier models", "AI model", "AI models", "AI agent", "AI agents", "agentic", "AI system",
        "AI systems", "chatbot", "chatbots", "deepfake", "deepfakes", "synthetic media", "facial recognition",
        "live facial recognition", "biometric", "biometrics", "automated decision-making",
        "automated decision making", "algorithm", "algorithms", "algorithmic", "predictive analytics",
        "AI Security Institute", "AI Safety Institute", "AI Opportunities Action Plan", "AI Bill",
        "AI regulation", "AI safety", "AI assurance", "Sovereign AI Unit", "i.AI", "Incubator for AI",
        "AI Exemplars", "AI adoption", "AI skills", "AI tutor", "AI tools", "AI-generated", "Humphrey AI",
        "AI generated", "autonomous systems", "robotics", "computer vision", "natural language processing")),
    Topic("cloud_compute", "Cloud, data centres and compute", w(
        "cloud computing", "cloud services", "cloud service", "cloud provider", "cloud providers",
        "public cloud", "private cloud", "hybrid cloud", "cloud first", "cloud migration", "cloud contract",
        "cloud contracts", "cloud infrastructure", "cloud storage", "cloud-based", "software as a service",
        "SaaS", "hyperscale", "hyperscaler", "data centre", "data centres", "data center", "data centers",
        "datacentre", "datacentres", "datacenter", "server farm", "compute", "compute capacity",
        "computing power", "supercomputer", "supercomputers", "supercomputing", "exascale",
        "AI Research Resource", "Isambard", "Isambard-AI", "Dawn supercomputer", "Compute Roadmap",
        "AI growth zone", "AI growth zones", "growth zone", "growth zones", "Data Centre Covenant",
        "National Policy Statement for Data Centres", "strategic data centre", "critical national infrastructure",
        "vendor lock-in", "vendor lock in", "lock-in", "egress fees", "semiconductor", "semiconductors",
        "microchip", "microchips", "computer chips", "AI chips", "AI Hardware Plan", "quantum computing",
        "quantum computer", "quantum computers")
        + (r"\bsovereign\s+(cloud|ai|compute|capabilit\w*|technolog\w*|data|digital|infrastructure)\b",
           r"\b(digital|data|technological|tech|cloud|ai|compute)\s+sovereignty\b",
           r"\bstrategic\s+autonomy\b", r"\bcloud\b(?=[^.]{0,80}\b(data|computing|service|provider|server|software|storage|IT|digital|contract)\w*)",
           r"\b(data|computing|IT|digital|software|server)\w*\b[^.]{0,80}\bcloud\b")),
    Topic("online_safety", "Online safety and social media", w(
        "online safety", "Online Safety Act", "online harm", "online harms", "harmful content",
        "illegal content", "Ofcom", "age verification", "age assurance", "age checks", "social media",
        "social media ban", "online scam", "online scams", "online fraud", "fraudulent advert",
        "fraudulent adverts", "scam adverts", "user-generated content", "content moderation",
        "misinformation", "disinformation", "online abuse", "cyberbullying", "VPN", "VPNs",
        "child sexual abuse material", "CSAM", "nudification", "intimate image abuse", "screen time",
        "smartphones", "smartphone ban", "app store", "app stores", "online platforms", "search engines")),
    Topic("copyright_ip", "Copyright and intellectual property", w(
        "copyright", "text and data mining", "intellectual property", "Intellectual Property Office",
        "licensing of creative works", "creative industries and AI", "AI and copyright", "AI training data",
        "training data", "web scraping", "rights holders", "rightsholders") + cs("TDM")),
    Topic("data_protection", "Data protection and privacy", w(
        "data protection", "Data (Use and Access) Act", "Data Use and Access Act", "UK GDPR", "GDPR",
        "Information Commissioner", "Information Commissioner's Office", "personal data",
        "data breach", "data breaches", "data sharing", "data-sharing", "privacy", "surveillance",
        "data adequacy", "adequacy decision", "international data transfers", "data transfers",
        "National Data Library", "single patient record", "federated data platform", "digital ID",
        "digital identity", "digital ID card", "GOV.UK One Login", "One Login", "GOV.UK Wallet") + cs("ICO")),
    Topic("cyber", "Cyber security and resilience", w(
        "cyber", "cyber security", "cybersecurity", "cyber-security", "cyber attack", "cyber attacks",
        "cyber-attack", "cyberattack", "cyberattacks", "cyber crime", "cybercrime", "cyber resilience",
        "Cyber Security and Resilience Bill", "Network and Information Systems", "NIS Regulations",
        "ransomware", "malware", "phishing", "hacking", "hacker", "hackers", "hacked", "denial of service",
        "zero-day", "vulnerability disclosure", "National Cyber Security Centre",
        "Cyber Essentials", "critical national infrastructure", "IT outage", "IT outages", "system outage",
        "service outage", "computer misuse", "Computer Misuse Act", "encryption", "end-to-end encryption",
        "encrypted", "Investigatory Powers", "Investigatory Powers Act", "technical capability notice",
        "post-quantum", "supply chain security", "software supply chain", "open source", "open-source",
        "legacy IT", "legacy systems") + cs("DDoS", "NCSC")
        + (r"\b(it|cloud|system|systems|software|digital|online|technology|network|internet|website|computer|email|365)\s+outages?\b",)),
    Topic("competition", "Digital competition and markets", w(
        "digital markets", "Digital Markets, Competition and Consumers Act", "DMCC", "DMCC Act",
        "strategic market status", "SMS designation", "conduct requirements", "Competition and Markets Authority",
        "cloud market investigation", "cloud services market", "software licensing", "licensing practices",
        "interoperability", "app store competition", "digital services tax", "online advertising",
        "subscription contracts", "subscription traps") + cs("CMA", "DST")),
    Topic("gov_digital", "Government digital, IT and procurement", w(
        "Government Digital Service", "Central Digital and Data Office", "digital and IT services",
        "digital, data and technology", "digital procurement", "digital technology", "digital transformation",
        "legacy IT systems", "IT systems", "IT system", "IT contract", "IT contracts", "IT supplier", "IT suppliers",
        "technology contract", "technology contracts", "technology supplier", "technology suppliers",
        "software licences", "software licenses", "software licence", "software license", "G-Cloud",
        "Crown Commercial Service", "Government Commercial Agency", "Technology Services 4", "Digital Outcomes",
        "Procurement Act", "public sector AI", "AI in the public sector", "digital government",
        "blueprint for modern digital government", "gov.uk app", "GOV.UK App", "digital services", "e-government",
        "electronic government", "Algorithmic Transparency Recording Standard", "spend on IT") + cs("GDS", "CDDO", "ATRS", "DDaT")),
    Topic("skills", "Digital skills and education technology", w(
        "digital skills", "digital literacy", "digital inclusion", "digital exclusion", "computing",
        "computer science", "coding", "STEM subjects", "STEM skills", "edtech", "education technology", "AI in education",
        "AI in schools", "tech skills", "technology skills", "AI skills", "TechFirst", "Skills England",
        "apprenticeships in technology", "data skills", "cyber skills") + cs("STEM")),
)

# Questions to these departments are always screened in (layer 2).
DEPARTMENTS = (
    "Department for Science, Innovation and Technology",
)
# Questions to these departments are screened in when they mention digital, data, IT or technology.
DEPARTMENTS_IF_DIGITAL = (
    "Cabinet Office", "Department for Digital, Culture, Media and Sport", "Department for Culture, Media and Sport",
    "Department for Business and Trade", "Department for Business, Innovation, Science and Trade",
    "Department for Energy Security and Net Zero", "Ministry of Housing, Communities and Local Government",
    "Treasury", "HM Treasury", "Home Office", "Department of Health and Social Care", "Department for Education",
)
DIGITAL_HINT = re.compile(
    r"\b(digital\w*|online|internet|technolog\w*|software|computer\w*|cyber\w*|tech|platforms?|apps?|websites?|"
    r"electronic|automat\w+|data (?:centre|center|protection|sharing|breach|system|platform)s?)\b"
    r"|(?-i:\bIT\b)", re.I)

# Members who consistently drive these issues: every question they ask is screened in (layer 3).
# Ids from the Members API; names for readability. Review quarterly.
WATCH_MEMBERS = {
    4124: "Dame Chi Onwurah (Chair, Commons Science, Innovation and Technology Committee)",
    3396: "Lord Clement-Jones (Lib Dem Lords spokesperson, AI and Digital)",
    4939: "Viscount Camrose (Shadow Cabinet Office Minister, AI and Cyber)",
    4785: "Dr Ben Spencer (Shadow Cabinet Office Minister)",
    1796: "Lord Taylor of Warwick",
    4909: "Lord Kamall (Shadow Health Minister, Lords)",
}

# Search terms for the Hansard API (results are re-screened with TOPICS).
SEARCH_TERMS = [
    "Microsoft", "Xbox", "LinkedIn", "GitHub", "Azure", "Copilot", "Google", "YouTube", "Amazon", "OpenAI",
    "ChatGPT", "Anthropic", "Nvidia", "Meta", "Palantir", "Oracle", "Capita", "big tech", "tech companies",
    "artificial intelligence", "AI", "algorithm", "chatbot", "deepfake", "facial recognition", "machine learning",
    "cloud", "data centre", "data centres", "compute", "supercomputer", "sovereign", "sovereignty", "growth zone",
    "semiconductor", "quantum", "vendor lock-in", "cyber", "ransomware", "hacking", "encryption",
    "Investigatory Powers", "Cyber Security and Resilience", "online safety", "Ofcom", "social media",
    "age verification", "online fraud", "scam", "copyright", "text and data mining", "intellectual property",
    "data protection", "GDPR", "Information Commissioner", "digital ID", "One Login", "single patient record",
    "federated data platform", "digital markets", "Competition and Markets Authority", "digital services tax",
    "subscription", "Government Digital Service", "IT systems", "legacy IT", "procurement", "digital skills",
    "computing", "edtech", "digital",
]

_COMPILED = tuple((t, tuple(re.compile(p, re.IGNORECASE) for p in t.patterns)) for t in TOPICS)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def to_plain_text(value: str | None) -> str:
    """Strip HTML tags and entities and collapse whitespace."""
    if not value:
        return ""
    text = _TAG_RE.sub(" ", value)
    text = html.unescape(text).replace("’", "'").replace("‘", "'")
    return _SPACE_RE.sub(" ", text).strip()


def match_topics(*texts: str | None, extra_terms: list[str] | None = None) -> dict[str, list[str]]:
    """Return {topic_label: [matched words]} for the combined texts (layer 1)."""
    plain = " ".join(to_plain_text(t) for t in texts if t)
    found: dict[str, list[str]] = {}
    for topic, regexes in _COMPILED:
        hits: list[str] = []
        for rx in regexes:
            m = rx.search(plain)
            if m:
                word = m.group(0).lower().strip()
                if word not in hits:
                    hits.append(word)
        if hits:
            found[topic.label] = hits[:8]
    if extra_terms:
        extra_hits = [t.lower() for t in extra_terms if t.strip() and any(re.search(p, plain, re.I) for p in w(t.strip()))]
        if extra_hits:
            found["Other keywords"] = extra_hits
    return found


def screen_question(q: dict) -> tuple[dict[str, list[str]], list[str]]:
    """Layers 1-3 for one written question. Returns (topics, layers that matched)."""
    texts = (q.get("heading"), q.get("questionText"), q.get("answerText"))
    topics = match_topics(*texts)
    layers = ["keyword"] if topics else []
    dept = q.get("answeringBodyName") or ""
    if dept in DEPARTMENTS:
        layers.append("department")
        topics.setdefault(f"{dept} business", [dept])
    elif dept in DEPARTMENTS_IF_DIGITAL and DIGITAL_HINT.search(" ".join(to_plain_text(t) for t in texts if t)):
        layers.append("department")
        topics.setdefault("Departmental digital business", [dept])
    mid = q.get("askingMemberId") or (q.get("askingMember") or {}).get("id")
    if mid in WATCH_MEMBERS:
        layers.append("watchlist")
        topics.setdefault("Watched member", [WATCH_MEMBERS[mid].split(" (")[0]])
    return topics, layers
