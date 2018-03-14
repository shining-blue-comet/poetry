from poetry.semver.constraints import MultiConstraint

from .builders import CompleteBuilder
from .builders import SdistBuilder
from .builders import WheelBuilder


class Builder:

    _FORMATS = {
        'sdist': SdistBuilder,
        'wheel': WheelBuilder,
        'all': CompleteBuilder
    }

    def __init__(self, poetry, io):
        self._poetry = poetry
        self._io = io

    def build(self, fmt: str):
        if fmt not in self._FORMATS:
            raise ValueError(f'Invalid format: {fmt}')

        builder = self._FORMATS[fmt](self._poetry, self._io)

        return builder.build()
