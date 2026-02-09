import json
import os
import subprocess
import sys


def read_version():
    if os.path.exists("VERSION"):
        with open("VERSION", "r", encoding="utf-8") as f:
            return f.read().strip()
    return "1.0.0"


def collect_plugin_dependencies():
    """
    Scans all plugins/manifest.json files and collects 'dependencies' field.
    """
    deps = set()
    plugins_dir = "plugins"
    if not os.path.exists(plugins_dir):
        return []

    for item in os.listdir(plugins_dir):
        manifest_path = os.path.join(plugins_dir, item, "manifest.json")
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                    plugin_deps = manifest.get("dependencies", [])
                    if isinstance(plugin_deps, list):
                        deps.update(plugin_deps)
            except Exception as e:
                print(f"Warning: Failed to parse manifest for {item}: {e}")

    # Also add standard modules used in core that might be missed by dynamic loader if any
    # But usually PyInstaller finds core ones.
    return sorted(list(deps))


def update_version_info(version):
    parts = version.split(".")
    while len(parts) < 4:
        parts.append("0")
    v_str = ", ".join(parts)
    v_dot = ".".join(parts)

    template_path = "file_version_info.txt"
    if not os.path.exists(template_path):
        print(f"Warning: {template_path} not found.")
        return

    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    content = content.replace("filevers=(1, 0, 0, 0)", f"filevers=({v_str})")
    content = content.replace("prodvers=(1, 0, 0, 0)", f"prodvers=({v_str})")
    content = content.replace(
        "StringStruct(u'FileVersion', u'1.0.0.0')",
        f"StringStruct(u'FileVersion', u'{v_dot}')",
    )
    content = content.replace(
        "StringStruct(u'ProductVersion', u'1.0.0.0')",
        f"StringStruct(u'ProductVersion', u'{v_dot}')",
    )

    with open("build_version_info.txt", "w", encoding="utf-8") as f:
        f.write(content)


def build():
    version = read_version()
    print(f"Building AgileTiles version {version}...")

    for d in ["plugins", "core", "ui"]:
        if not os.path.isdir(d):
            print(f"Error: Directory '{d}' not found!")
            sys.exit(1)

    update_version_info(version)
    sys.setrecursionlimit(5000)

    cmd = [
        "pyinstaller",
        "--noconsole",
        "--onedir",
        "--name",
        "AgileTiles",
        "--clean",
    ]

    # ===== 收集插件依赖 (Hidden Imports) =====
    plugin_deps = collect_plugin_dependencies()
    if plugin_deps:
        print(f"Collected plugin dependencies: {', '.join(plugin_deps)}")
        for dep in plugin_deps:
            cmd.extend(["--hidden-import", dep])

    # ===== 收集 qfluentwidgets 资源 =====
    cmd.extend(["--collect-all", "qfluentwidgets"])

    # ===== 注入程序图标 =====
    icon_path = os.path.join(os.getcwd(), "icon.ico")
    if os.path.exists(icon_path):
        cmd.extend(["--icon", icon_path])
        print("Using application icon:", icon_path)
    else:
        print("Warning: icon.ico not found. Using default icon.")

    # ===== 数据目录 =====
    cmd.extend(
        [
            "--add-data",
            f"plugins{os.pathsep}plugins",
            "--add-data",
            f"core{os.pathsep}core",
            "--add-data",
            f"ui{os.pathsep}ui",
            "--add-data",
            f"VERSION{os.pathsep}.",
            "main.py",
        ]
    )

    print(f"Running command: {' '.join(cmd)}")

    try:
        pyinstaller_bin = os.path.join(
            os.path.dirname(sys.executable), "pyinstaller.exe"
        )
        if os.path.exists(pyinstaller_bin):
            cmd[0] = pyinstaller_bin

        subprocess.run(cmd, check=True)
        print("Build successful!")

    except subprocess.CalledProcessError as e:
        print(f"Build failed with exit code {e.returncode}")
        sys.exit(1)

    finally:
        if os.path.exists("build_version_info.txt"):
            os.remove("build_version_info.txt")

    print(" ".join(cmd))


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    pyinstaller_bin = os.path.join(os.path.dirname(sys.executable), "pyinstaller.exe")
    if not os.path.exists(pyinstaller_bin):
        print("PyInstaller not found in venv. Installing...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"], check=True
        )

    build()
