import pytest

from gcode_sim.errors import LexError, UnsupportedFeatureError
from gcode_sim.lexer import tokenize, tokenize_macro_stmt


def test_basic_block():
    blocks = tokenize("G0 X10.0 Z-5.0;")
    assert len(blocks) == 1
    b = blocks[0]
    assert b.seq_no is None
    assert not b.skip
    words = {(w.address, w.value) for w in b.words}
    assert words == {("G", "0"), ("X", "10.0"), ("Z", "-5.0")}


def test_sequence_number_extracted():
    blocks = tokenize("N010 G01 X5.0;")
    assert blocks[0].seq_no == 10
    assert [(w.address, w.value) for w in blocks[0].words] == [("G", "01"), ("X", "5.0")]


def test_comment_stripped():
    blocks = tokenize("G0 X10.0 (rapid to start) Z5.0;")
    words = {(w.address, w.value) for w in blocks[0].words}
    assert words == {("G", "0"), ("X", "10.0"), ("Z", "5.0")}


def test_block_skip():
    blocks = tokenize("/G0 X10.0;")
    assert blocks[0].skip is True
    assert [(w.address, w.value) for w in blocks[0].words] == [("G", "0"), ("X", "10.0")]


def test_multiple_statements_per_line():
    blocks = tokenize("G0 X10.0; G01 Z-5.0;")
    assert len(blocks) == 2


def test_multiple_lines():
    blocks = tokenize("G0 X10.0;\nG01 Z-5.0;\n")
    assert len(blocks) == 2


def test_macro_syntax_rejected():
    with pytest.raises(UnsupportedFeatureError):
        tokenize("#1=100;")


def test_macro_keyword_rejected():
    with pytest.raises(UnsupportedFeatureError):
        tokenize("GOTO 10;")


def test_unrecognized_token_raises_lex_error():
    # This is the legacy Phase-0 tokenize() path, kept strict for its own
    # tests -- the real pipeline (tokenize_macro_stmt, tested just below)
    # is intentionally more lenient about stray noise characters.
    with pytest.raises(LexError):
        tokenize("G0 @@@ X10.0;")


def test_tokenize_macro_stmt_skips_unrecognized_noise_characters():
    # The tokenizer parser.py actually uses skips a stray character it
    # doesn't recognize (real-world NC files sometimes carry vendor-
    # specific punctuation/control characters) instead of raising --
    # the surrounding valid tokens should still come through intact.
    tokens = tokenize_macro_stmt("G0 @@@ X10.0", line_no=1)
    kinds_and_text = [(t.kind, t.text) for t in tokens]
    assert kinds_and_text == [("NAME", "G"), ("NUMBER", "0"), ("NAME", "X"), ("NUMBER", "10.0")]


def test_no_g_word_block():
    """A block that just carries new coordinates (relies on modal G)."""
    blocks = tokenize("X20.0 Z-10.0;")
    words = {(w.address, w.value) for w in blocks[0].words}
    assert words == {("X", "20.0"), ("Z", "-10.0")}
