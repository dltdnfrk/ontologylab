"""Adversarial Atom-feed fixtures for the round-2 QA suite (throwaway)."""

GOOD_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query: search_query=all:databases</title>
  <entry>
    <id>http://arxiv.org/abs/9101.00001v1</id>
    <title>Round-Two Storage Engines</title>
    <summary>A second-pass survey of embedded storage engines.</summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/9101.00002v1</id>
    <title>Round-Two Query Planning</title>
    <summary>Plan-space pruning under cardinality misestimation.</summary>
  </entry>
</feed>
"""

# Entry with title+summary but NO <id> element (F1 target).
NO_ID_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Round-Two Orphan Without Identifier</title>
    <summary>This entry has no id element at all.</summary>
  </entry>
</feed>
"""

# One valid entry + one id-less entry: exactly one document must land.
MIXED_ID_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/9102.00001v1</id>
    <title>Round-Two Valid Entry</title>
    <summary>Has an id; must be ingested.</summary>
  </entry>
  <entry>
    <title>Round-Two Id-less Entry</title>
    <summary>No id; must never become a row.</summary>
  </entry>
</feed>
"""

# Not well-formed XML: guaranteed ParseError.
TRUNCATED_FEED = GOOD_FEED[: len(GOOD_FEED) // 2]

# Well-formed feed with zero entries.
EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query: no results</title>
</feed>
"""

FAKE_HTML_PAGE = """<html>
  <head><title>Round-Two Fake Docs Page</title></head>
  <body><p>Some extractable documentation text for round two.</p></body>
</html>
"""
