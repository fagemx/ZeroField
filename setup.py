"""Bundle runtime resources without maintaining duplicate source asset trees."""
from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.errors import SetupError


class BuildRuntimeResources(build_py):
    def run(self):
        super().run()
        root = Path(__file__).resolve().parent
        sql = root / "db"
        frontend = root / "static" / "projects"
        if not list(sql.glob("*.sql")) or not (frontend / "index.html").is_file() or not list((frontend / "assets").glob("*.js")):
            raise SetupError("Missing runtime SQL or browser bundle. Run npm ci and npm run build in ui/ before building OpenBench.")
        target = Path(self.build_lib) / "openbench_data"
        (target / "db").mkdir(parents=True, exist_ok=True)
        for source in sql.glob("*.sql"):
            shutil.copy2(source, target / "db" / source.name)
        # Only current source assets belong in a new wheel, even after a rebuild.
        packaged_frontend = target / "static" / "projects"
        if packaged_frontend.exists():
            if not packaged_frontend.resolve().is_relative_to(target.resolve()):
                raise SetupError("Refusing to replace browser assets outside the build package directory")
            shutil.rmtree(packaged_frontend)
        shutil.copytree(frontend, packaged_frontend)


setup(cmdclass={"build_py": BuildRuntimeResources})
