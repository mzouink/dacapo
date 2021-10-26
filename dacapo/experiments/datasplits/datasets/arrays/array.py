from funlib.geometry import Coordinate, Roi

from abc import ABC, abstractmethod


class Array(ABC):

    @property
    @abstractmethod
    def axes(self):
        """Returns the axes of this dataset as a string of charactes, as they
        are indexed. Permitted characters are:

            * ``zyx`` for spatial dimensions
            * ``c`` for channels
            * ``s`` for samples
        """
        pass

    @property
    @abstractmethod
    def dims(self) -> int:
        """Returns the number of spatial dimensions."""
        pass

    @property
    @abstractmethod
    def voxel_size(self) -> Coordinate:
        """The size of a voxel in physical units."""
        pass

    @property
    @abstractmethod
    def roi(self) -> Roi:
        """The total ROI of this array, in world units."""
        pass
