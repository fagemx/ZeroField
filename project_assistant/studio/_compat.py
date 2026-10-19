"""Live legacy mock seams, without rebinding implementation globals or copying state."""
import sys

# Populated once by studio.__init__, after the acyclic implementation imports.
OWNERS = {}
ORIGINALS = {}


def __getattr__(name):
    if name not in OWNERS:
        raise AttributeError(name)
    owner = OWNERS[name]
    # A facade/package patch overrides a dependency only while explicitly present.
    for module_name in ("project_assistant.limb_worker", "project_assistant.studio"):
        module = sys.modules.get(module_name)
        if module is not None:
            namespace = vars(module)
            if name in namespace and namespace[name] is not ORIGINALS[name]:
                return namespace[name]
    return getattr(owner, name)
