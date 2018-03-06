import poetry.packages

from poetry.semver.constraints import Constraint
from poetry.semver.constraints import MultiConstraint
from poetry.semver.constraints.base_constraint import BaseConstraint
from poetry.semver.version_parser import VersionParser


class Dependency:

    def __init__(self,
                 name: str,
                 constraint: str,
                 optional: bool = False,
                 category: str = 'main',
                 allows_prereleases: bool = False):
        self._name = name.lower()
        self._pretty_name = name
        self._parser = VersionParser()

        try:
            self._constraint = self._parser.parse_constraints(constraint)
        except ValueError:
            self._constraint = self._parser.parse_constraints('*')

        self._pretty_constraint = constraint
        self._optional = optional
        self._category = category
        self._allows_prereleases = allows_prereleases

        self._python_versions = '*'
        self._python_constraint = self._parser.parse_constraints('*')
        self._platform = '*'
        self._platform_constraint = self._parser.parse_constraints('*')

        self._extras = []

    @property
    def name(self):
        return self._name

    @property
    def constraint(self):
        return self._constraint
    
    @property
    def pretty_constraint(self):
        return self._pretty_constraint

    @property
    def pretty_name(self):
        return self._pretty_name

    @property
    def category(self):
        return self._category

    @property
    def python_versions(self):
        return self._python_versions

    @python_versions.setter
    def python_versions(self, value: str):
        self._python_versions = value
        self._python_constraint = self._parser.parse_constraints(value)

    @property
    def python_constraint(self):
        return self._python_constraint

    @property
    def platform(self) -> str:
        return self._platform

    @platform.setter
    def platform(self, value: str):
        self._platform = value

    @property
    def platform_constraint(self):
        return self._platform_constraint

    @property
    def extras(self) -> list:
        return self._extras

    def allows_prereleases(self):
        return self._allows_prereleases

    def is_optional(self):
        return self._optional

    def is_vcs(self):
        return False

    def accepts(self, package: 'poetry.packages.Package') -> bool:
        """
        Determines if the given package matches this dependency.
        """
        return (
            self._name == package.name
            and self._constraint.matches(Constraint('=', package.version))
            and (not package.is_prerelease() or self.allows_prereleases())
        )

    def to_pep_508(self) -> str:
        requirement = f'{self.pretty_name}'

        if isinstance(self.constraint, MultiConstraint):
            requirement += ','.join(
                [str(c).replace(' ', '') for c in self.constraint.constraints]
            )
        else:
            requirement += str(self.constraint).replace(' ', '')

        # Markers
        markers = []

        # Python marker
        if self.python_versions != '*':
            python_constraint = self.python_constraint
            marker = 'python_version'
            if isinstance(python_constraint, MultiConstraint):
                marker += ','.join(
                    [str(c).replace(' ', '') for c in python_constraint.constraints]
                )
            else:
                marker += str(python_constraint).replace(' ', '')

            markers.append(marker)

        if markers:
            requirement += f'; {" and ".join(markers)}'

        return requirement

    def activate(self):
        """
        Set the dependency as mandatory.
        """
        self._optional = False

    def __eq__(self, other):
        if not isinstance(other, Dependency):
            return NotImplemented

        return self._name == other.name and self._constraint == other.constraint

    def __hash__(self):
        return hash((self._name, self._pretty_constraint))

    def __str__(self):
        return f'{self._pretty_name} ({self._pretty_constraint})'

    def __repr__(self):
        return f'<Dependency {str(self)}>'
