import unittest
from array import array
from pathlib import Path

from plugins.thiefbook.reader import ThiefBookReader


class ThiefBookReaderPaginationTest(unittest.TestCase):
    def _reader(self, content, page_length, is_english=False, line_break=" "):
        reader = ThiefBookReader()
        reader.txt_path = str(Path(__file__))
        reader._content = content
        reader.page_length = page_length
        reader.is_english = is_english
        reader.line_break = line_break
        reader._paginate()
        return reader

    def test_pages_are_materialized_only_when_requested(self):
        reader = self._reader("abcdefghij", 3)

        self.assertIsInstance(reader._page_ranges, array)
        self.assertEqual(reader._page_count, 4)
        self.assertFalse(hasattr(reader, "_pages"))
        self.assertEqual(reader.get_current_text(), "abc")
        reader.current_page = 4
        self.assertEqual(reader.get_current_text(), "j")

    def test_newlines_and_whitespace_match_existing_display_behavior(self):
        reader = self._reader("  ab\ncd  ", 20, line_break="|")

        self.assertEqual(reader.get_current_text(), "ab|cd")

    def test_english_pages_do_not_split_words(self):
        reader = self._reader("alpha beta gamma", 7, is_english=True)

        self.assertEqual(reader._page_count, 2)
        self.assertEqual(reader.get_current_text(), "alpha beta")
        reader.next_page()
        self.assertEqual(reader.get_current_text(), "gamma")

    def test_search_uses_indexed_page_slices(self):
        reader = self._reader("first second third", 6, is_english=True)

        self.assertTrue(reader.search_keyword("third"))
        self.assertEqual(reader.get_current_text(), "third")


if __name__ == "__main__":
    unittest.main()
