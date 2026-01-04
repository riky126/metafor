from setuptools import setup, find_packages

setup(
    name="metafor-cli",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "setuptools>=80.9.0",
        "wheel>=0.45.1",
        "watchdog",
        "libsass",
    ],
    entry_points={
        "console_scripts": [
            "metafor=metafor_cli.main:main",
        ],
    },
    package_data={
        "metafor_cli": [
            "templates/starter_app/**/*",
        ],
    },
)
