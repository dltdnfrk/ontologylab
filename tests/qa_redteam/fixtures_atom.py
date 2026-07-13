"""Adversarial Atom-feed fixtures for the paper_api red-team suite."""

ATOM_NS = "http://www.w3.org/2005/Atom"

GOOD_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query: search_query=all:databases</title>
  <entry>
    <id>http://arxiv.org/abs/9001.00001v1</id>
    <title>Write-Ahead Logging Revisited</title>
    <summary>A survey of WAL implementations in embedded storage engines.</summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/9001.00002v1</id>
    <title>Cost-Based Join Ordering</title>
    <summary>Cardinality estimation errors and their effect on join plans.</summary>
  </entry>
</feed>
"""

# Same titles/summaries (=> identical raw_text => identical content_hash),
# but DIFFERENT entry ids (=> different source_uri).
GOOD_FEED_ALT_IDS = GOOD_FEED.replace(
    "http://arxiv.org/abs/9001.00001v1", "http://mirror.example/abs/9001.00001v1"
).replace(
    "http://arxiv.org/abs/9001.00002v1", "http://mirror.example/abs/9001.00002v1"
)

# Cut mid-element: guaranteed not well-formed.
TRUNCATED_FEED = GOOD_FEED[: len(GOOD_FEED) // 2]

WRONG_NAMESPACE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://example.com/definitely-not-atom">
  <entry>
    <id>http://arxiv.org/abs/9002.00001v1</id>
    <title>Should Never Be Ingested</title>
    <summary>Namespace does not match Atom; parser must not pick this up.</summary>
  </entry>
</feed>
"""

# Deeply nested but SMALL (no entity expansion): stress the parser shape.
_DEPTH = 200
DEEP_NESTED_FEED = (
    '<?xml version="1.0"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
    + "<x>" * _DEPTH
    + "deep"
    + "</x>" * _DEPTH
    + "</feed>"
)

# Entry with title+summary but NO <id> element.
NO_ID_ENTRY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Orphan Without Identifier</title>
    <summary>This entry has no id element at all.</summary>
  </entry>
</feed>
"""

# A well-formed (XML-parseable) HTML error page.
HTML_ERROR_WELLFORMED = """<html>
  <head><title>503 Service Unavailable</title></head>
  <body><p>Service temporarily unavailable.</p></body>
</html>
"""

# Typical real-world (NOT well-formed XML) HTML error page.
HTML_ERROR_MALFORMED = """<!DOCTYPE html>
<html>
<body>
<h1>503 Service Unavailable<br>
<p>upstream connect error
</body>
</html>
"""

# Small internal-entity expansion (bomb-shaped but tiny by design).
ENTITY_FEED = """<?xml version="1.0"?>
<!DOCTYPE feed [
  <!ENTITY a "expandme">
  <!ENTITY b "&a;&a;">
]>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/9003.00001v1</id>
    <title>Entity Expansion Probe</title>
    <summary>&b;&b;</summary>
  </entry>
</feed>
"""
