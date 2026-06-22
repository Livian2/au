"""Auto-fetchers for the automatable rows (spec §2, Phase 1/2).

Every fetcher is best-effort and degrades gracefully: if the network is
unavailable the tool still runs on stored/manual data. Nothing here ever touches
a brokerage account (§8 out-of-scope).
"""
