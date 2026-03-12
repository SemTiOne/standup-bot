from setuptools import find_packages, setup  # type: ignore[import]

with open("README.md", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="standupbot",
    version="0.1.0",
    description="Generate daily standup summaries from your git history using local or free cloud LLMs.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="SemTiOne",
    license="MIT",
    python_requires=">=3.9",
    packages=find_packages(exclude=["tests*"]),
    install_requires=[
        "ollama>=0.1.7,<1.0.0",
        "groq>=0.4.0,<1.0.0",
        "gitpython>=3.1.40,<4.0.0",
        "pyperclip>=1.8.2,<2.0.0",
        "rich>=13.0.0,<14.0.0",
        "requests>=2.31.0,<3.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "standup=standup.main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Environment :: Console",
        "Topic :: Software Development :: Version Control :: Git",
    ],
)