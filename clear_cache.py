import os
import shutil

def delete_pycache(root_dir):
    for root, dirs, files in os.walk(root_dir):
        if "__pycache__" in dirs:
            pycache_path = os.path.join(root, "__pycache__")
            print(f"Removing {pycache_path}")
            try:
                shutil.rmtree(pycache_path)
            except Exception as e:
                print(f"Failed to remove {pycache_path}: {e}")

if __name__ == "__main__":
    delete_pycache(".")
