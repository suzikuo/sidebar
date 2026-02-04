import os
import shutil
from pathlib import Path


class HostFileHandler:
    """
    Handles reading and writing to the Windows hosts file.
    """

    def __init__(self):
        self.hosts_path = (
            Path(os.environ["SystemRoot"]) / "System32" / "drivers" / "etc" / "hosts"
        )
        self.backup_path = self.hosts_path.parent / "hosts.bak"

    def read_hosts(self) -> str:
        """Reads the content of the hosts file."""
        if not self.hosts_path.exists():
            return ""

        try:
            with open(self.hosts_path, "r", encoding="utf-8") as f:
                return f.read()
        except PermissionError:
            return "# Error: Permission denied reading hosts file."
        except Exception as e:
            return f"# Error reading hosts file: {e}"

    def write_hosts(self, content: str) -> bool:
        """
        Writes content to the hosts file.
        Attempts to write directly; if permission denied, attempts to elevate via UAC.
        Returns True if write successful or elevation requested, False on error.
        """
        import ctypes
        import tempfile

        try:
            # Create a backup first
            if self.hosts_path.exists():
                shutil.copy2(self.hosts_path, self.backup_path)

            # Try writing directly
            with open(self.hosts_path, "w", encoding="utf-8") as f:
                f.write(content)
            return True

        except PermissionError:
            print("[HostFileHandler] Permission denied. Attempting to elevate...")
            try:
                # Write to a temp file first
                with tempfile.NamedTemporaryFile(
                    mode="w", delete=False, encoding="utf-8", suffix=".tmp"
                ) as tmp:
                    tmp.write(content)
                    temp_path = Path(tmp.name)

                # Command to copy temp file to hosts path
                # cmd /c copy /Y "temp_path" "hosts_path"
                cmd = "cmd.exe"
                params = f'/c copy /Y "{temp_path}" "{self.hosts_path}"'

                # Execute with 'runas' to request admin privileges
                # SW_HIDE = 0 to hide the command window
                ret = ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", cmd, params, None, 0
                )

                if ret > 32:
                    return True
                else:
                    print(f"[HostFileHandler] Elevation failed with code {ret}")
                    return False

            except Exception as e:
                print(f"[HostFileHandler] Elevation error: {e}")
                return False

        except Exception as e:
            print(f"[HostFileHandler] Error writing hosts file: {e}")
            return False

    def is_writable(self) -> bool:
        """Checks if the hosts file is writable."""
        return os.access(self.hosts_path, os.W_OK)
