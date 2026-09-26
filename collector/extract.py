"""Pull token references ($TICKER, keywords, contract addresses) out of tweet text."""
import re

CASHTAG = re.compile(r"\$([A-Za-z][A-Za-z0-9]{1,11})\b")
EVM_ADDR = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
# Solana mint: base58, 32-44 chars. Require at least one digit and one letter to cut
# false positives on long plain words.
SOL_ADDR = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
URL = re.compile(r"https?://\S+")


def build_alias_patterns(aliases):
    pats = []
    for symbol, words in (aliases or {}).items():
        for w in words:
            if re.fullmatch(r"[A-Za-z0-9 ]+", w):
                pats.append((symbol.upper(), re.compile(rf"(?<![A-Za-z0-9$]){re.escape(w)}(?![A-Za-z0-9])", re.I)))
            else:  # CJK keywords have no word boundaries
                pats.append((symbol.upper(), re.compile(re.escape(w))))
    return pats


def extract_tokens(text, alias_patterns=(), ignore=()):
    """Return (symbols, addresses) referenced in `text`."""
    ignore = {s.upper() for s in ignore}
    clean = URL.sub(" ", text or "")
    symbols = [m.upper() for m in CASHTAG.findall(clean)]
    for sym, pat in alias_patterns:
        if pat.search(clean):
            symbols.append(sym)
    symbols = [s for s in dict.fromkeys(symbols) if s not in ignore and not s.isdigit()]

    addresses = EVM_ADDR.findall(clean)
    for cand in SOL_ADDR.findall(clean):
        if any(ch.isdigit() for ch in cand) and any(ch.isalpha() for ch in cand):
            addresses.append(cand)
    return symbols, list(dict.fromkeys(addresses))
