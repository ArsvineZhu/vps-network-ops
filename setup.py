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
        for resource in (Path(self.build_lib) / "vps_ops").rglob("*"):
            if not resource.is_file() or "__pycache__" in resource.parts:
                continue
            resource.write_text(
                resource.read_text(encoding="utf-8-sig"), encoding="utf-8", newline="\n"
            )


setup(cmdclass={"build_py": Build})
