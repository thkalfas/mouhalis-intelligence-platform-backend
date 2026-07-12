"""Pipeline filters. Each stage reads Items in one status, writes them in the
next; stages never call each other directly (AD-1). The runner wires them.
"""
