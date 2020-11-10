from distutils.core import setup


long_description = ''

setup(
    name="pyiwctl",
    version="20201005",
    author="Inemajo",
    author_email="inemajo@inemajo.eu",
    description="IWD client interface",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/inemajo/pyiwctl",
    packages=["pyiwctl"],
    classifiers=[
        "Programming Language :: Python :: 3",
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',

    install_requires=[
        'dbus_next',
    ]
)
