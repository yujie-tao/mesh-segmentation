# from setuptools import setup
# import numpy
# from Cython.Build import cythonize

# print(numpy.get_include())

# setup(
#     ext_modules=cythonize("dijkstra.pyx"),
#     include_dirs=[numpy.get_include()],
# )

from setuptools import setup, Extension
import numpy
from Cython.Build import cythonize

# Define the extension module
extensions = [
    Extension(
        "dijkstra",
        sources=["dijkstra.pyx"],
        include_dirs=[numpy.get_include()],
        # You can add additional libraries or directories if needed
        # libraries=[],
        # library_dirs=[],
    )
]

# Setup configuration
setup(
    ext_modules=cythonize(extensions),
)
