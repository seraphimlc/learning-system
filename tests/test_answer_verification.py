import unittest

from learning_system.answer_verification import is_math_equivalent


class TestMathEquivalent(unittest.TestCase):
    def test_equivalent_fraction_and_decimal(self):
        self.assertTrue(is_math_equivalent("3/4 + 5/6", "19/12"))  # 3/4+5/6 = 19/12
        self.assertTrue(is_math_equivalent("1.5", "3/2"))
        self.assertTrue(is_math_equivalent("6/4", "1.5"))

    def test_mismatch_returns_false(self):
        self.assertFalse(is_math_equivalent("1/2", "2/3"))
        self.assertFalse(is_math_equivalent("3", "4"))

    def test_invalid_input_returns_false(self):
        self.assertFalse(is_math_equivalent("abc", "1"))
        self.assertFalse(is_math_equivalent("", "1"))


if __name__ == "__main__":
    unittest.main()
