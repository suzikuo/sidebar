import secrets
import string


class PasswordGenerator:
    """
    Generates strong passwords based on configuration.
    """

    def generate(
        self,
        length: int = 16,
        use_digits: bool = True,
        use_symbols: bool = True,
        use_upper: bool = True,
        use_lower: bool = True,
    ) -> str:
        secure_random = secrets.SystemRandom()

        if length < 4:
            length = 4  # Minimum length constraint

        chars = ""
        if use_lower:
            chars += string.ascii_lowercase
        if use_upper:
            chars += string.ascii_uppercase
        if use_digits:
            chars += string.digits
        if use_symbols:
            chars += "!@#$%^&*"

        if not chars:
            return ""

        # Ensure at least one character from each selected category
        password = []
        if use_lower:
            password.append(secure_random.choice(string.ascii_lowercase))
        if use_upper:
            password.append(secure_random.choice(string.ascii_uppercase))
        if use_digits:
            password.append(secure_random.choice(string.digits))
        if use_symbols:
            password.append(secure_random.choice("!@#$%^&*"))

        # Fill the rest
        while len(password) < length:
            password.append(secure_random.choice(chars))

        # Shuffle to avoid predictable patterns
        secure_random.shuffle(password)

        # Trim to exact length (in case minimum requirements pushed it over, though unlikely with min=4)
        return "".join(password[:length])
