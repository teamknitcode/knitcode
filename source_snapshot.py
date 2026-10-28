"""JSON-compatible facts with process-local, non-serialized syntax trees.

One scan feeds both semantic engines. Deserialized JSON still works through
the normal source-text parsing fallback; this is not a global cache.
"""


class SourceSnapshot(dict):
    def __init__(self, *args, syntax_trees=None, metadata_sources=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.syntax_trees = {} if syntax_trees is None else syntax_trees
        self.metadata_sources = {} if metadata_sources is None else metadata_sources
