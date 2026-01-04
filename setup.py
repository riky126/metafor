from setuptools import setup, find_packages

setup(
    name="metafor",
    version="0.0.1",
    description="The Metafor Framework",
    author="Metafor Team",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "libsass",
    ],
)
