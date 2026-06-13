import unittest

from item_name_utils import canonicalize_item_name, normalize_item_name


class NormalizeItemNameTests(unittest.TestCase):
    def test_maps_jumbo_pickle_to_pickles(self):
        self.assertEqual(normalize_item_name("Jumbo Pickle"), "pickles")

    def test_maps_jumbo_pickles_to_pickles_case_insensitively(self):
        self.assertEqual(normalize_item_name("  JUMBO PICKLES  "), "pickles")

    def test_keeps_existing_normalization_for_other_items(self):
        self.assertEqual(normalize_item_name("  Nachos---Cheese "), "nachos - cheese")

    def test_canonicalizes_price_prefixed_aliases(self):
        self.assertEqual(canonicalize_item_name("$1 Dog"), "Hot Dog")
        self.assertEqual(canonicalize_item_name("$3 Brats"), "Brats")
        self.assertEqual(canonicalize_item_name("$5 Hamburger"), "Hamburgers")


if __name__ == "__main__":
    unittest.main()
