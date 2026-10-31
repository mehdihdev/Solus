# mypy: ignore-errors
"""Fixture (SOLUSDEV-321 P6): the environment the policy was trained in. Its observation space is
24 wide and its action space 6 wide. The software reader parses it with `ast` only; nothing here is
imported or run."""

from spaces import Box


class ArmEnv:
    def __init__(self) -> None:
        self.observation_space = Box(low=-1.0, high=1.0, shape=(24,))
        self.action_space = Box(low=-1.0, high=1.0, shape=(6,))
