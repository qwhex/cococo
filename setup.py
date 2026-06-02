from typing import Optional

from setuptools import setup, find_packages


package_name = 'cognitive_complexity'


def get_version() -> Optional[str]:
    with open('cognitive_complexity/__init__.py', 'r') as f:
        lines = f.readlines()
    for line in lines:
        if line.startswith('__version__'):
            return line.split('=')[-1].strip().strip("'")
    return None


def get_long_description() -> str:
    with open('README.md') as f:
        return f.read()


setup(
    name=package_name,
    description='Library to calculate Python functions cognitive complexity via code',
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
    keywords='cognitive-complexity flake8 cococo',
    version=get_version(),
    author='Ilya Lebedev',
    author_email='melevir@gmail.com',
    install_requires=['setuptools'],
    url='https://github.com/qwhex/cococo',
    license='MIT',
    py_modules=[package_name],
    entry_points={
        'console_scripts': [
            'cococo = cognitive_complexity.cli:main',
        ],
    },
    zip_safe=False,
)
