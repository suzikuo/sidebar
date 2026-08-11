import unittest

from plugins.windows_controls.service import WindowsControlService, parse_power_plans


class FakeUser32:
    def __init__(self):
        self.keys = []
        self.locked = False

    def keybd_event(self, *args):
        self.keys.append(args)

    def LockWorkStation(self):
        self.locked = True
        return True


class WindowsControlsServiceTest(unittest.TestCase):
    def test_power_plan_output_is_parsed(self):
        output = """
Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced) *
Power Scheme GUID: a1841308-3541-4fab-bc81-f71556f20b4a  (Power saver)
"""
        plans = parse_power_plans(output)

        self.assertEqual(len(plans), 2)
        self.assertTrue(plans[0]["active"])
        self.assertEqual(plans[1]["name"], "Power saver")

    def test_actions_use_argument_arrays_and_validate_power_plan(self):
        commands = []
        opened = []
        user32 = FakeUser32()

        def runner(command):
            commands.append(command)
            return ""

        service = WindowsControlService(
            runner=runner,
            startfile=opened.append,
            user32=user32,
        )
        service.perform("mute")
        service.perform("display")
        service.perform("brightness", 120)
        service.perform("power_plan", "381b4222-f694-41f0-9685-ff5bb260df2e")

        self.assertEqual(len(user32.keys), 2)
        self.assertEqual(opened, ["ms-settings:display"])
        self.assertIn("Brightness=100", commands[0][-1])
        self.assertEqual(commands[1][:2], ["powercfg.exe", "/setactive"])
        with self.assertRaises(ValueError):
            service.perform("power_plan", "bad-guid")


if __name__ == "__main__":
    unittest.main()
