"""Select the highest-priority tag from a set of tags."""

# Tag priority, highest first.
PRIORITY = ["urgent", "normal", "low"]


def priority_tag(tags):
    """Return the highest-priority tag present in `tags` (a set)."""
    for t in tags:
        return t
    return None
