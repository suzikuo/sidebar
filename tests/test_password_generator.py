import string
import unittest
from unittest.mock import patch

from plugins.toolbox.features.password_generator.logic import PasswordGenerator


class _DeterministicSystemRandom:
    def __init__(self):
        self.choice_calls = []
        self.shuffle_calls = 0

    def choice(self, sequence):
        self.choice_calls.append(sequence)
        return sequence[0]

    def shuffle(self, values):
        self.shuffle_calls += 1
        values.reverse()


class PasswordGeneratorTest(unittest.TestCase):
    def setUp(self):
        self.generator = PasswordGenerator()

    def test_password_contains_each_enabled_character_category(self):
        password = self.generator.generate(length=24)

        self.assertEqual(len(password), 24)
        self.assertTrue(any(char in string.ascii_lowercase for char in password))
        self.assertTrue(any(char in string.ascii_uppercase for char in password))
        self.assertTrue(any(char in string.digits for char in password))
        self.assertTrue(any(char in "!@#$%^&*" for char in password))

    def test_disabled_categories_are_not_used(self):
        password = self.generator.generate(
            length=32,
            use_digits=False,
            use_symbols=False,
            use_upper=False,
            use_lower=True,
        )

        self.assertEqual(len(password), 32)
        self.assertTrue(all(char in string.ascii_lowercase for char in password))

    def test_no_enabled_categories_returns_empty_string(self):
        password = self.generator.generate(
            use_digits=False,
            use_symbols=False,
            use_upper=False,
            use_lower=False,
        )

        self.assertEqual(password, "")

    def test_uses_system_random_for_selection_and_shuffle(self):
        secure_random = _DeterministicSystemRandom()

        with patch(
            "plugins.toolbox.features.password_generator.logic.secrets.SystemRandom",
            return_value=secure_random,
        ):
            password = self.generator.generate(length=8)

        self.assertEqual(len(password), 8)
        self.assertGreaterEqual(len(secure_random.choice_calls), 8)
        self.assertEqual(secure_random.shuffle_calls, 1)


if __name__ == "__main__":
    unittest.main()
