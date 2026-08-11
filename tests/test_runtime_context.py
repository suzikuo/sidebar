import __main__
import unittest

from core.runtime_context import (
    clear_application,
    get_application,
    register_application,
)


class RuntimeContextTest(unittest.TestCase):
    def tearDown(self):
        try:
            application = get_application()
        except RuntimeError:
            return
        clear_application(application)

    def test_registered_application_is_available_until_cleared(self):
        missing = object()
        previous = getattr(__main__, "app_instance", missing)
        if previous is not missing:
            delattr(__main__, "app_instance")

        def restore_main_application():
            if previous is missing:
                if hasattr(__main__, "app_instance"):
                    delattr(__main__, "app_instance")
            else:
                __main__.app_instance = previous

        self.addCleanup(restore_main_application)
        application = object()

        register_application(application)
        self.assertIs(get_application(), application)
        self.assertIs(__main__.app_instance, application)

        clear_application(application)
        self.assertFalse(hasattr(__main__, "app_instance"))
        with self.assertRaisesRegex(RuntimeError, "not available"):
            get_application()

    def test_different_application_cannot_replace_active_registration(self):
        register_application(object())

        with self.assertRaisesRegex(RuntimeError, "already registered"):
            register_application(object())

    def test_clearing_application_restores_existing_main_module_value(self):
        previous = object()
        application = object()
        __main__.app_instance = previous

        def remove_main_application():
            if hasattr(__main__, "app_instance"):
                delattr(__main__, "app_instance")

        self.addCleanup(remove_main_application)

        register_application(application)
        self.assertIs(__main__.app_instance, application)

        clear_application(application)
        self.assertIs(__main__.app_instance, previous)


if __name__ == "__main__":
    unittest.main()
