"""Source adapters — the only code that talks to the outside world.

Every Source (Tier 1/2/3) implements SourceAdapter (AD-3). Adapters never import
pipeline or each other; they meet downstream only at the SourceRecord contract.
"""
