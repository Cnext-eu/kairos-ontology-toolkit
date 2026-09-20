### Fixed
- **The Engineering Pack shows what a measure actually computes again.** TMDL wraps a
  multi-line DAX expression in a ``` fence, and the parser stored the fence markers as
  part of the expression. The pack previews a measure from the first line of its
  expression — which was the fence — so every multi-line measure rendered as an empty
  code fence and nothing else: on one real model, 53 of 59 measures listed a name and no
  definition. Fenced expressions are now read to their closing delimiter and dedented,
  so the DAX keeps its indentation and blank lines, and the concept-mapping worksheet no
  longer carries fence markers inside each `expression:` value. Reading to an explicit
  delimiter also removes a latent truncation, where a DAX line resembling a measure
  property would cut the expression short.
