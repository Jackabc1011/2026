"""Smart-money wallet activity: what configured wallets have been buying.

EVM chains via Etherscan V2 (ETHERSCAN_API_KEY), Solana via Helius (HELIUS_API_KEY).
Returns buy records:
  {label, wallet, chain, weight, symbol, address, amount, time, tx_url}
"""
from datetime import datetime, timedelta, timezone

from ..http import get_json

EVM_CHAIN_IDS = {"eth": 1, "bsc": 56, "base": 8453, "arbitrum": 42161}
EXPLORERS = {
    "eth": "https://etherscan.io/tx/", "bsc": "https://bscscan.com/tx/",
    "base": "https://basescan.org/tx/", "arbitrum": "https://arbiscan.io/tx/",
    "solana": "https://solscan.io/tx/",
}
# Quote assets a swap pays with; receiving these is not a "buy" signal.
SOLANA_QUOTE_MINTS = {
    "So11111111111111111111111111111111111111112",   # wSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}


def _iso_ts(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_wallet_buys(wallets, lookback_hours, etherscan_key, helius_key, ignore=()):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    buys, errors = [], []
    for w in wallets:
        chain = w.get("chain", "eth").lower()
        try:
            if chain == "solana":
                if not helius_key:
                    errors.append(f"{w.get('label')}: 缺少 HELIUS_API_KEY")
                    continue
                data = get_json(
                    f"https://api.helius.xyz/v0/addresses/{w['address']}/transactions",
                    params={"api-key": helius_key, "type": "SWAP", "limit": 50})
                buys += parse_helius(data, w, cutoff)
            elif chain in EVM_CHAIN_IDS:
                if not etherscan_key:
                    errors.append(f"{w.get('label')}: 缺少 ETHERSCAN_API_KEY")
                    continue
                data = get_json("https://api.etherscan.io/v2/api", params={
                    "chainid": EVM_CHAIN_IDS[chain], "module": "account", "action": "tokentx",
                    "address": w["address"], "page": 1, "offset": 100, "sort": "desc",
                    "apikey": etherscan_key})
                if data.get("status") != "1" and data.get("message") != "No transactions found":
                    raise RuntimeError(str(data.get("result"))[:200])
                buys += parse_etherscan(data, w, cutoff, ignore)
            else:
                errors.append(f"{w.get('label')}: 不支持的链 {chain}")
        except Exception as e:  # noqa: BLE001 - one bad wallet shouldn't stop the rest
            errors.append(f"{w.get('label')}: {e}")
    if errors and not buys:
        raise RuntimeError("; ".join(errors))
    for e in errors:
        print(f"[warn] wallet {e}")
    return buys


def _base(w, chain):
    return {"label": w.get("label") or w["address"][:8], "wallet": w["address"],
            "chain": chain, "weight": float(w.get("weight", 1.0))}


def parse_etherscan(data, w, cutoff, ignore=()):
    ignore = {s.upper() for s in ignore}
    me = w["address"].lower()
    chain = w.get("chain", "eth").lower()
    out = []
    for t in data.get("result") or []:
        if not isinstance(t, dict) or t.get("to", "").lower() != me:
            continue
        ts = int(t.get("timeStamp", 0))
        if datetime.fromtimestamp(ts, timezone.utc) < cutoff:
            continue
        sym = (t.get("tokenSymbol") or "").upper()
        if not sym or sym in ignore:
            continue
        dec = int(t.get("tokenDecimal") or 18)
        out.append({**_base(w, chain), "symbol": sym, "address": t.get("contractAddress"),
                    "amount": int(t.get("value", "0")) / 10 ** dec, "time": _iso_ts(ts),
                    "tx_url": EXPLORERS[chain] + t.get("hash", "")})
    return out


def parse_helius(data, w, cutoff):
    out = []
    for tx in data or []:
        ts = tx.get("timestamp") or 0
        if datetime.fromtimestamp(ts, timezone.utc) < cutoff:
            continue
        for tr in tx.get("tokenTransfers") or []:
            if tr.get("toUserAccount") != w["address"] or tr.get("mint") in SOLANA_QUOTE_MINTS:
                continue
            out.append({**_base(w, "solana"), "symbol": None, "address": tr.get("mint"),
                        "amount": tr.get("tokenAmount"), "time": _iso_ts(ts),
                        "tx_url": EXPLORERS["solana"] + tx.get("signature", "")})
    return out
