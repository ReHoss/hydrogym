import os

from firedrake import Mesh

mesh_dir = os.path.abspath(f"{__file__}/..")

FLUID = 1
INLET = 2
FREESTREAM = 3
OUTLET = 4
CYLINDER = 5


def load_mesh(name="medium"):
    return Mesh(f"{mesh_dir}/{name}.msh", name="mesh")