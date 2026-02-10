import argparse
import os
import shutil
import sys
import zipfile


def package_as_zip(plugin_dir, output_dir):
    """Packages a plugin directory into a .zip file."""
    if not os.path.exists(plugin_dir):
        print(f"Error: Directory '{plugin_dir}' not found.")
        return None

    manifest_path = os.path.join(plugin_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        print(f"Error: manifest.json not found in '{plugin_dir}'.")
        return None

    plugin_name = os.path.basename(os.path.normpath(plugin_dir))
    zip_filename = f"{plugin_name}.zip"
    zip_path = os.path.join(output_dir, zip_filename)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(plugin_dir):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, plugin_dir)
                zipf.write(abs_path, os.path.join(plugin_name, rel_path))

    print(f"Successfully created zip plugin: {zip_path}")
    return zip_path


def compile_to_pyd(path, output_dir):
    """Compiles a single .py file into a .pyd file using Cython."""
    if not os.path.exists(path):
        print(f"Error: Path '{path}' not found.")
        return None

    # Resolve entry point if path is a directory
    entry_file = path
    if os.path.isdir(path):
        manifest_path = os.path.join(path, "manifest.json")
        if os.path.exists(manifest_path):
            try:
                import json

                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                    entry = manifest.get("entry", "plugin.py")
                    entry_file = os.path.join(path, entry)
            except Exception as e:
                print(f"Warning: Failed to read manifest.json: {e}")
                entry_file = os.path.join(path, "plugin.py")
        else:
            entry_file = os.path.join(path, "plugin.py")

    if not os.path.isfile(entry_file):
        print(f"Error: Entry file '{entry_file}' not found.")
        return None

    try:
        import Cython
    except ImportError:
        print(
            "Error: Cython is not installed. Use 'pip install Cython' to enable .pyd compilation."
        )
        return None

    from Cython.Build import cythonize
    from setuptools import setup

    module_name = os.path.splitext(os.path.basename(entry_file))[0]

    # We need to temporarily change CWD or trick setuptools
    old_cwd = os.getcwd()
    file_dir = os.path.dirname(os.path.abspath(entry_file))
    os.chdir(file_dir)

    try:
        # Create a tiny setup call
        # Note: This will create a 'build' folder and some temp files
        sys.argv = ["setup.py", "build_ext", "--inplace"]
        setup(
            ext_modules=cythonize(
                os.path.basename(entry_file), language_level="3", quiet=True
            ),
            script_args=["build_ext", "--inplace"],
        )

        # Find the generated .pyd
        pyd_file = None
        for f in os.listdir("."):
            # Match module_name.pyd or module_name.something.pyd
            if f.startswith(module_name) and f.endswith(".pyd"):
                pyd_file = os.path.abspath(f)
                break

        if pyd_file:
            target_path = os.path.join(output_dir, os.path.basename(pyd_file))
            shutil.copy2(pyd_file, target_path)
            print(f"Successfully compiled .pyd: {target_path}")
            return target_path
        else:
            print(f"Error: Failed to find generated .pyd file for '{module_name}'.")
            return None

    except Exception as e:
        print(f"Error during compilation: {e}")
        return None
    finally:
        os.chdir(old_cwd)


def main():
    parser = argparse.ArgumentParser(description="Agile Tiles 插件打包工具")
    parser.add_argument(
        "path", help="插件目录 (打包为zip) 或 plugin.py 文件 (编译为pyd)"
    )
    parser.add_argument("--type", choices=["zip", "pyd"], help="强制指定打包类型")
    parser.add_argument("--out", default=".", help="输出目录")

    args = parser.parse_args()

    if not os.path.exists(args.out):
        os.makedirs(args.out)

    target_type = args.type
    if not target_type:
        if os.path.isdir(args.path):
            target_type = "zip"
        else:
            target_type = "pyd"

    if target_type == "zip":
        package_as_zip(args.path, args.out)
    else:
        compile_to_pyd(args.path, args.out)


if __name__ == "__main__":
    main()
