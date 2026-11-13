import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class Build(build_py):
    def run(self):
        super().run()
        target = Path(self.build_lib) / "vps_ops/deploy/assets/system"
        for existing in target.rglob("*"):
            if existing.is_file():
                existing.chmod(0o644)
        shutil.copytree(
            "system",
            target,
            dirs_exist_ok=True,
            copy_function=shutil.copyfile,
            ignore=shutil.ignore_patterns("*.o", "__pycache__"),
        )


setup(cmdclass={"build_py": Build})
