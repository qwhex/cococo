
from pathlib import Path

from setuptools import find_packages, setup


def get_version() -> str | None:
    for line in Path('cognitive_complexity/__init__.py').read_text().splitlines():
        if line.startswith('__version__'):
            return line.split('=')[-1].strip().strip("'")
    return None


def get_long_description() -> str:
    return Path('README.md').read_text()


setup(
    # Distribution name kept as the importable package name: the parent
    # data_pipeline depends on it as `cognitive-complexity`. The repo and CLI
    # are branded `cococo` (see README).
    name='cognitive_complexity',
    description='Library and CLI to compute the cognitive complexity of Python functions',
    classifiers=[
        'Environment :: Console',
        'Operating System :: OS Independent',
        'Topic :: Software Development :: Documentation',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Software Development :: Quality Assurance',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Programming Language :: Python :: 3.14',
    ],
    long_description=get_long_description(),
    long_description_content_type='text/markdown',
    packages=find_packages(),
    python_requires='>=3.10',
    include_package_data=True,
    keywords='cognitive-complexity cli flake8 cococo',
    version=get_version(),
    author='Mice Pápai',
    author_email='hello@micepapai.com',
    url='https://github.com/qwhex/cococo',
    license='MIT',
    entry_points={
        'console_scripts': [
            'cococo = cognitive_complexity.cli:main',
        ],
    },
    zip_safe=False,
)
