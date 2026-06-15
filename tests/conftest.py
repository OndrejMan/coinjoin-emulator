import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

if importlib.util.find_spec("docker") is None:
    docker_module = types.ModuleType("docker")
    docker_models_module = types.ModuleType("docker.models")
    docker_containers_module = types.ModuleType("docker.models.containers")

    class ImageNotFound(Exception):
        pass

    class NotFound(Exception):
        pass

    class APIError(Exception):
        def __init__(
            self,
            message: str = "",
            response: object | None = None,
            explanation: str | None = None,
        ) -> None:
            super().__init__(message)
            self.response = response
            self.explanation = explanation

    setattr(docker_module, "from_env", lambda: None)
    setattr(
        docker_module,
        "errors",
        SimpleNamespace(
            ImageNotFound=ImageNotFound,
            NotFound=NotFound,
            APIError=APIError,
        ),
    )
    setattr(docker_containers_module, "Container", object)

    sys.modules["docker"] = docker_module
    sys.modules["docker.models"] = docker_models_module
    sys.modules["docker.models.containers"] = docker_containers_module
