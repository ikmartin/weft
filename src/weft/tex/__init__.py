"""The LaTeX layer: a tokenizer, environment trees, macros, sectioning, the preamble closure, digest headers, the `.aux` reader and a latexmk runner.

Nothing here knows about a corpus. It reads a directory of LaTeX files and says what is in them; `weft.extract` turns that into results. Ported from loom's scanner, which is the other implementation of the digest contract, so a divergence between the two tools is a bug in one of them rather than a difference of design.
"""
